"""Offline Intel FCFF engine. USD millions; no third-party dependencies.

Run python model.py; inspect output/report.html or output/results.json.
Historical observations and judgments are separated in docs/evidence-ledger.md.
"""
import argparse
import copy
import csv
from datetime import date, datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load_inputs(path=None):
    return json.loads(Path(path or ROOT / 'inputs.json').read_text(encoding='utf-8'))

def check_close(actual, expected, label, tolerance=1e-6):
    if not math.isfinite(actual) or not math.isfinite(expected) or abs(actual-expected)>tolerance:
        raise ValueError(f'{label}: actual {actual:.8f}, expected {expected:.8f}')

def check_row(r):
    for key, value in r.items():
        if isinstance(value,(float,int)) and not math.isfinite(value):
            raise ValueError(f'Nonfinite {key}')
    assets = sum(r[k] for k in ['cash','investments','receivables','inventory','ppe','intangibles','other_assets'])
    claims = sum(r[k] for k in ['payables','debt','other_liabilities','parent_equity','nci'])
    check_close(assets,claims,f"{r['period']} balance sheet")
    if 'cfo' in r:
        check_close(r['cash']-r['opening_cash'],r['cfo']+r['cfi']+r['cff'],f"{r['period']} cash flow")
    if r['investments'] < -1e-6 or r['debt'] < -1e-6 or r['ppe'] < -1e-6:
        raise ValueError('Impossible negative asset/debt balance')
    # A cash shortfall is retained and flagged, never financed by an invisible plug.
    return assets-claims

def initial_state(inp):
    h=inp['historical']['H12026']
    keys=['cash','investments','receivables','inventory','ppe','intangibles','payables','debt','other_liabilities','parent_equity','nci']
    r={k:float(h[k]) for k in keys}
    r['other_assets']=h['assets']-sum(r[k] for k in ['cash','investments','receivables','inventory','ppe','intangibles'])
    r['period']='June 27 actual'
    check_row(r)
    # Equity settlement convention: cancel the noncash derivative and include
    # escrow shares in diluted shares. Never also deduct the derivative in bridge.
    r['other_liabilities']-=h['escrow_derivative']
    r['parent_equity']+=h['escrow_derivative']
    r['period']='June 27 normalized'
    check_row(r)
    return r

def step(o, revenue, annual_revenue, c, index, fraction, period, inp):
    r={'period':period,'fraction':fraction,'revenue':revenue,'opening_cash':o['cash']}
    r['cost_of_sales']=revenue*(1-c['gross_margin'][index])
    r['gross_profit']=revenue-r['cost_of_sales']
    r['rd']=revenue*c['rd_ratio'][index]
    r['sga']=revenue*c['sga_ratio']
    # Recurring restructuring reserve: judgment, retained instead of assuming zero.
    r['restructuring']=300*fraction
    r['ebit']=r['gross_profit']-r['rd']-r['sga']-r['restructuring']
    r['depreciation']=o['ppe']*(11782/105741)*fraction
    r['amortization']=min(o['intangibles'],938*fraction)
    r['da']=r['depreciation']+r['amortization']
    r['interest']=o['debt']*inp['debt_cost']*fraction
    r['pretax']=r['ebit']-r['interest']
    r['tax']=max(0,r['pretax'])*inp['tax_rate']
    r['net_income']=r['pretax']-r['tax']
    r['nci_income']=max(0,r['net_income'])*0.10
    r['parent_net_income']=r['net_income']-r['nci_income']
    r['nci_distribution']=r['nci_income']
    r['capex']=c['capex'][index]*fraction
    # Transition to target turnover over the half-year, not instantaneously at June.
    transition=min(1,fraction*2) if index==0 else 1
    annual_cogs=annual_revenue*(1-c['gross_margin'][index])
    r['receivables']=o['receivables']+(annual_revenue*c['receivable_days']/365-o['receivables'])*transition
    r['inventory']=o['inventory']+(annual_cogs*c['inventory_days']/365-o['inventory'])*transition
    r['payables']=o['payables']+(annual_cogs*c['payable_days']/365-o['payables'])*transition
    r['delta_nwc']=(r['receivables']-o['receivables']+r['inventory']-o['inventory']-r['payables']+o['payables'])
    r['ppe']=o['ppe']+r['capex']-r['depreciation']
    r['intangibles']=o['intangibles']-r['amortization']
    r['other_assets']=o['other_assets']
    r['other_liabilities']=o['other_liabilities']
    r['repayment']=min(o['debt'],2000*fraction)
    r['debt']=o['debt']-r['repayment']
    r['parent_equity']=o['parent_equity']+r['parent_net_income']
    r['nci']=o['nci']+r['nci_income']-r['nci_distribution']
    r['cfo']=r['net_income']+r['da']-r['delta_nwc']
    r['cff']=-r['repayment']-r['nci_distribution']
    preliminary_cash=o['cash']+r['cfo']-r['capex']+r['cff']
    r['investment_sales']=min(o['investments'],max(0,inp['minimum_cash']-preliminary_cash))
    r['investments']=o['investments']-r['investment_sales']
    r['cfi']=-r['capex']+r['investment_sales']
    r['cash']=o['cash']+r['cfo']+r['cfi']+r['cff']
    r['funding_gap']=max(0,inp['minimum_cash']-r['cash'])
    r['unlevered_tax']=max(0,r['ebit'])*inp['tax_rate']
    r['nopat']=r['ebit']-r['unlevered_tax']
    r['fcff']=r['nopat']+r['da']-r['capex']-r['delta_nwc']
    r['total_assets']=sum(r[k] for k in ['cash','investments','receivables','inventory','ppe','intangibles','other_assets'])
    r['total_liabilities_equity']=sum(r[k] for k in ['payables','debt','other_liabilities','parent_equity','nci'])
    r['balance_gap']=check_row(r)
    return r

def project(inp, case='base'):
    c=inp['cases'][case]
    start=date(2026,6,27); end=date(2026,12,26); val=date.fromisoformat(inp['valuation_date'])
    if not start<val<end:
        raise ValueError('This historical bridge supports June 27 < valuation date < December 26, 2026')
    pre_days=(val-start).days; rem_days=(end-val).days; total_days=(end-start).days
    o=initial_state(inp)
    # Half-year flow allocation and latest disclosed balance roll to valuation date.
    pre=step(o,c['h2_revenue']*pre_days/total_days,c['h2_revenue']*2,c,0,pre_days/365,'Pre-valuation estimate',inp)
    stub=step(pre,c['h2_revenue']*rem_days/total_days,c['h2_revenue']*2,c,0,rem_days/365,'2026 remaining stub',inp)
    rows=[stub]; o=stub
    annual=inp['historical']['H12026']['revenue']+c['h2_revenue']
    for j,year in enumerate(range(2027,2032),1):
        annual*=1+c['growth'][j-1]
        o=step(o,annual,annual,c,j,1,f'FY{year}',inp)
        rows.append(o)
    return pre,rows

def wacc(inp):
    equity=inp['price']*inp['basic_shares']
    debt=inp['historical']['H12026']['debt']
    ke=inp['risk_free']+inp['beta']*inp['equity_risk_premium']
    dw=debt/(debt+equity)
    return dict(ke=ke,kd=inp['debt_cost'],debt_weight=dw,equity_weight=1-dw,
                wacc=ke*(1-dw)+inp['debt_cost']*(1-inp['tax_rate'])*dw)

def dcf(flows, times, discount, growth, bridge, shares):
    nums=list(flows)+list(times)+[discount,growth,bridge,shares]
    if not all(math.isfinite(x) for x in nums):
        raise ValueError('DCF refuses NaN/infinity')
    if discount<=growth or discount<=0 or growth<=-1 or shares<=0 or len(flows)!=len(times) or not flows:
        raise ValueError('Require WACC > growth, positive shares, and matching nonempty flows/times')
    if any(t<=0 for t in times) or times!=sorted(times):
        raise ValueError('Discount times must be positive and increasing')
    if flows[-1]<=0:
        raise ValueError('Positive sustainable terminal FCFF required; no fabricated terminal value')
    pv=sum(f/(1+discount)**t for f,t in zip(flows,times))
    terminal=flows[-1]*(1+growth)/(discount-growth)
    pv_terminal=terminal/(1+discount)**times[-1]
    ev=pv+pv_terminal
    equity=ev+bridge
    return dict(pv_explicit=pv,terminal_value=terminal,pv_terminal=pv_terminal,
                enterprise_value=ev,bridge_adjustment=bridge,common_equity=equity,
                raw_per_share=equity/shares,per_share=max(0,equity/shares),
                terminal_share=pv_terminal/ev if ev else None,wacc=discount,terminal_growth=growth,shares=shares)

def evaluate(inp,case='base'):
    pre,rows=project(inp,case)
    shares=inp['basic_shares']+inp['escrow_shares']+inp['award_shares']
    b=dict(excess_cash=max(0,pre['cash']-inp['minimum_cash']),short_term_investments=pre['investments'],
           equity_investments=inp['equity_investments'],debt=-pre['debt'],nci=-inp['nci_value'],other_claims=-inp['other_claims'])
    shift=inp['cases'][case]['wacc_shift']; g=inp['cases'][case]['terminal_growth']
    times=[(date(2026,12,26)-date.fromisoformat(inp['valuation_date'])).days/365+i for i in range(6)]
    flows=[r['fcff'] for r in rows]
    try:
        v=dcf(flows,times,wacc(inp)['wacc']+shift,g,sum(b.values()),shares)
        reinvest=rows[-1]['capex']-rows[-1]['da']+rows[-1]['delta_nwc']
        v['terminal_reinvestment']=reinvest
        v['implied_terminal_roic']=g*rows[-1]['nopat']/reinvest if reinvest>0 else None
    except ValueError as e:
        v={'error':str(e),'per_share':None}
    gaps=[r['funding_gap'] for r in [pre]+rows]
    return dict(case=case,name=inp['cases'][case]['name'],prevaluation=pre,statements=rows,
                bridge=b,times=times,valuation=v,max_funding_gap=max(gaps),financeable=max(gaps)<1e-6)

def comparables(inp):
    rows=[]
    for p in inp['peers']:
        market_cap=p['price']*p['shares']
        ev=market_cap+p['debt']+p['nci']+p['other_claims']-p['cash_and_st']-p['nonoperating_investments']
        rows.append(dict(**p,market_cap=market_cap,enterprise_value=ev,ev_sales=ev/p['revenue'],pe=p['price']/p['eps'] if p['eps']>0 else None))
    target=rows[0]; peers=rows[1:]
    offset=target['market_cap']-target['enterprise_value']
    prices=[(p['ev_sales']*target['revenue']+offset)/target['shares'] for p in peers]
    return dict(rows=rows,diagnostic_intel_ev_sales_range=[min(prices),max(prices)],
                status='Lagged annual-balance reference; not initiation-grade current EV. No averaging with DCF.')

def analyze(inp):
    cases={c:evaluate(inp,c) for c in inp['cases']}
    base=cases['base']; b=base['valuation']; grid=[]
    for w in [b['wacc']-0.02,b['wacc']-0.01,b['wacc'],b['wacc']+0.01,b['wacc']+0.02]:
        for g in [0.015,0.025,0.035]:
            v=dcf([r['fcff'] for r in base['statements']],base['times'],w,g,sum(base['bridge'].values()),b['shares'])
            grid.append(dict(wacc=w,growth=g,per_share=v['per_share'],raw_per_share=v['raw_per_share']))
    # Algebraic reverse DCF: hold explicit flows fixed, solve perpetuity FCFF.
    required_ev=inp['price']*b['shares']-sum(base['bridge'].values())
    required_next=(required_ev-b['pv_explicit'])*(1+b['wacc'])**base['times'][-1]*(b['wacc']-b['terminal_growth'])
    last=base['statements'][-1]
    next_revenue=last['revenue']*(1+b['terminal_growth'])
    next_da=last['da']*(1+b['terminal_growth'])
    next_capex=last['capex']*(1+b['terminal_growth'])
    next_wc=last['delta_nwc']*(1+b['terminal_growth'])
    required_ebit=(required_next-next_da+next_capex+next_wc)/(1-inp['tax_rate'])
    reverse=dict(required_fy2032_fcff=required_next,base_fy2032_fcff=last['fcff']*(1+b['terminal_growth']),
                 required_ebit_margin=required_ebit/next_revenue,required_ev=required_ev,
                 description='Only terminal FCFF changes; explicit flows, discount rate, growth and bridge fixed. EBIT margin holds base reinvestment fixed.')
    stresses={}
    for name,mutate in [
        ('Capex overrun +4bn annually',lambda x:[x['cases']['base']['capex'].__setitem__(i,v+4000) for i,v in enumerate(x['cases']['base']['capex'])]),
        ('Margin recovery -5 percentage points',lambda x:x['cases']['base'].update(gross_margin=[v-0.05 for v in x['cases']['base']['gross_margin']])),
        ('Minority claims +50 percent',lambda x:x.update(nci_value=x['nci_value']*1.5)),
        ('Investment holdings valued at zero',lambda x:x.update(equity_investments=0)),
        ('Foundry control loss warrants exercised',lambda x:x.update(award_shares=x['award_shares']+241,equity_investments=x['equity_investments']+4820)),
    ]:
        changed=copy.deepcopy(inp); mutate(changed); s=evaluate(changed)
        stresses[name]=dict(valuation=s['valuation'],max_funding_gap=s['max_funding_gap'],financeable=s['financeable'],
                            action='Do not initiate' if not s['financeable'] else 'Watch / defer')
    valid=[c['valuation']['per_share'] for c in cases.values() if c['valuation']['per_share'] is not None]
    return dict(valuation_date=inp['valuation_date'],price=inp['price'],units='USD millions except per-share USD; shares millions',
                decision='Watch / defer',decision_horizon='12-24 month monitoring; five full forecast years plus remaining-2026 stub',
                wacc_components=wacc(inp),cases=cases,sensitivity=grid,reverse_dcf=reverse,comparables=comparables(inp),
                stresses=stresses,scenario_range=[min(valid),max(valid)],inputs=inp)

def fmt(v):
    if v is None: return 'NM / unavailable'
    return f'{v:,.2f}' if isinstance(v,(float,int)) else str(v)

def table(headers, rows):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(fmt(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'

def report(result):
    r=result; parts=['<!doctype html><html><head><meta charset="utf-8"><title>Intel committee evidence</title><style>body{font:16px/1.5 Segoe UI,Arial,sans-serif;max-width:1280px;margin:36px auto;padding:0 22px;color:#17263c;background:#f5f7fa}h1,h2{color:#173b64}section{background:white;padding:24px;margin:20px 0;border:1px solid #d9e2ec;border-radius:8px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:7px;border-bottom:1px solid #dce3ed;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#e8eff6}.lead{font-size:22px}a{color:#13588b}select{padding:8px}details{margin-top:15px} .scroll{overflow-x:auto}@media print{body{background:white;margin:0}section{break-inside:avoid}}</style></head><body>']
    inp=r['inputs'];base_inputs=inp['cases']['base']
    parts+=['<h1>Intel | Investment committee evidence</h1>',f'<p>As of {r["valuation_date"]} close | NASDAQ: INTC | USD | No existing position</p>',
    f'<section><p class="lead"><b>Watch / defer.</b> Conditional modeled range ${r["scenario_range"][0]:.0f}-${r["scenario_range"][1]:.0f} per diluted-equivalent share; observed close ${r["price"]:.2f}.</p><p>Do not initiate at the observed price. The range is scenario-dependent, not a confidence interval. Estimated interim bridge, minority valuations and dilution require further diligence. Funding failure changes watch to do not initiate. A zero floored equity residual does not assert zero option or liquidation value.</p><p>Initiation gate: price at least 25% below supported base value; two reported quarters with gross margin at least 41%; positive cash generation after all equipment payments; fully reconciled claims and dilution. Do not treat the price gate alone as authorization to buy.</p></section>']
    parts+=['<section><h2>Causal cases</h2>',table(['Case','2031 revenue','2031 EBIT','2031 FCFF','WACC','Value/share','TV/EV','Funding gap'],[[k,c['statements'][-1]['revenue'],c['statements'][-1]['ebit'],c['statements'][-1]['fcff'],f"{c['valuation'].get('wacc',0):.2%}",c['valuation']['per_share'],f"{c['valuation'].get('terminal_share',0):.1%}",c['max_funding_gap']] for k,c in r['cases'].items()]),'<p>See inputs.json and the assumption-challenge record for values, basis, challenges and reversal evidence.</p></section>']
    parts+=['<section><h2>Material inputs: facts versus judgments</h2>',table(['Input','Base value','Basis'],[
        ['Observed common-share close',f'${inp["price"]:.2f}',f'{inp["valuation_date"]} regular-session Close; Stock Analysis'],
        ['H2 2026 revenue',base_inputs['h2_revenue'],'Judgment; base originally repeats July Q3 guidance midpoint in Q4'],
        ['2027-2031 growth',', '.join(f'{x:.1%}' for x in base_inputs['growth']),'Judgment: fading recovery, not organic guidance'],
        ['Gross margin path',', '.join(f'{x:.1%}' for x in base_inputs['gross_margin']),'Q3 41% guidance; subsequent recovery judgments'],
        ['R&D / SG&A',f'{base_inputs["rd_ratio"][0]:.1%} to {base_inputs["rd_ratio"][-1]:.1%} / {base_inputs["sga_ratio"]:.1%}','Judgments informed by interim expenses'],
        ['Annual cash capex',', '.join(fmt(x) for x in base_inputs['capex']),'Judgment; FY2025 equipment payments 17,672'],
        ['Inventory / receivable / payable days',f'{base_inputs["inventory_days"]} / {base_inputs["receivable_days"]} / {base_inputs["payable_days"]}','Judgments; capital-payable classification unresolved'],
        ['Risk-free / beta / ERP',f'{inp["risk_free"]:.2%} / {inp["beta"]:.2f} / {inp["equity_risk_premium"]:.1%}','Dated Treasury fact / judgment / course assumption'],
        ['Cost of debt / tax',f'{inp["debt_cost"]:.1%} / {inp["tax_rate"]:.1%}','Marginal borrowing and tax judgments'],
        ['Terminal growth',f'{base_inputs["terminal_growth"]:.1%}','Nominal perpetuity judgment; no margin step-up'],
        ['Diluted-equivalent shares',r['cases']['base']['valuation']['shares'],'Basic + escrow + award proxy; see inputs.json'],
        ['NCI / other claims',f'{inp["nci_value"]:,.0f} / {inp["other_claims"]:,.0f}','Book-value proxy / judgment reserve'],
    ]),'<p>Source dates and exact locators are in docs/evidence-ledger.md. Forecast judgments were assembled retrospectively on October 19 using only facts available by September 1.</p></section>']
    parts+=['<section><h2>Three statements and FCFF</h2><label>Scenario <select id="case" onchange="document.querySelectorAll(\'.case\').forEach(x=>x.hidden=x.id!==this.value)"><option>base</option><option>low</option><option>high</option></select></label>']
    groups={'Income statement':['revenue','cost_of_sales','gross_profit','rd','sga','restructuring','ebit','interest','pretax','tax','net_income','nci_income','parent_net_income'],
            'Balance sheet':['cash','investments','receivables','inventory','ppe','intangibles','other_assets','total_assets','payables','debt','other_liabilities','parent_equity','nci','total_liabilities_equity'],
            'Cash flow and valuation cash flow':['net_income','da','delta_nwc','cfo','capex','investment_sales','cfi','repayment','nci_distribution','cff','opening_cash','cash','nopat','fcff','funding_gap','balance_gap']}
    for key,c in r['cases'].items():
        parts.append(f'<div class="case" id="{key}" {"hidden" if key!="base" else ""}>')
        for title,fields in groups.items():
            parts+=['<h3>'+title+'</h3><div class="scroll">',table(['USD million']+[x['period'] for x in c['statements']],[[f.replace('_',' ')]+[x[f] for x in c['statements']] for f in fields]),'</div>']
        parts+=['<h3>Enterprise to equity bridge</h3>',table(['Component','USD million'],list(c['bridge'].items())),f'<p>Raw equity residual/share: {fmt(c["valuation"].get("raw_per_share"))}; diluted-equivalent shares: {fmt(c["valuation"].get("shares"))}. Reported EPS shares are not the valuation denominator.</p></div>']
    parts+=['</section><section><h2>WACC and terminal-growth sensitivity</h2>',table(['WACC','g','USD/share'],[[f'{x["wacc"]:.2%}',f'{x["growth"]:.1%}',x['per_share']] for x in r['sensitivity']]),'<h3>Reverse DCF</h3>',table(['Expectation','Value'],list(r['reverse_dcf'].items())),'</section><section><h2>Named what-if tests</h2>',table(['Shock','USD/share','Funding gap','Action'],[[k,v['valuation']['per_share'],v['max_funding_gap'],v['action']] for k,v in r['stresses'].items()]),'</section>']
    parts+=['<section><h2>Comparable companies</h2>',table(['Company','Annual-end shares','Annual sales','GAAP EPS','Sep 1 close','EV/sales','P/E'],[[p[k] for k in ['ticker','shares','revenue','eps','price','ev_sales','pe']] for p in r['comparables']['rows']]),f'<p>Mechanical Intel EV/sales diagnostic: ${r["comparables"]["diagnostic_intel_ev_sales_range"][0]:.0f}-${r["comparables"]["diagnostic_intel_ev_sales_range"][1]:.0f}. These are lagged annual-balance multiples. Fabless economics and stale balance snapshots prevent interpreting this as the recommendation range. Intel reported P/E is NM. No mechanical average.</p></section>',
    '<section><h2>Evidence and limitations</h2><p><a href="../docs/evidence-ledger.md">Evidence ledger</a> | <a href="../docs/assumption-challenges.md">Assumption challenges</a> | <a href="../docs/validation-and-ai-use.md">Validation and AI use</a> | <a href="../README.md">Reproduction instructions</a> | <a href="results.json">Full machine-readable result</a></p><p>Operating leases remain operating expenses. A $5bn claims reserve covers deferred compensation and unresolved financing/lease/vendor obligations; it is a judgment, not a verified fair-value total. Consolidated forecasts assume cash-equivalent employee compensation and a 10% NCI earnings/distribution proxy. Current share awards and contingent escrow dilution use a conservative proxy. No future government receipts, acquisitions, or external foundry customer windfall are credited. Full limitations are in the evidence ledger.</p></section></body></html>']
    return '\n'.join(parts)

def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs');p.add_argument('--out',default=str(ROOT/'output'));p.add_argument('--break-cash',action='store_true');a=p.parse_args()
    inp=load_inputs(a.inputs)
    if a.break_cash:
        pre,rows=project(inp);rows[0]['cash']+=100;check_row(rows[0]);raise AssertionError('Break test did not fail')
    result=analyze(inp); out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    (out/'report.html').write_text(report(result),encoding='utf-8')
    with (out/'statements.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['case']+list(result['cases']['base']['statements'][0])
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for case,c in result['cases'].items():
            w.writerows(dict(case=case,**row) for row in c['statements'])
    stamp={'run_utc':datetime.now(timezone.utc).isoformat(),'inputs_sha256':hashlib.sha256(json.dumps(inp,sort_keys=True).encode()).hexdigest()}
    (out/'run-metadata.json').write_text(json.dumps(stamp,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['decision','valuation_date','price','scenario_range','wacc_components','reverse_dcf']},indent=2))
    for name,c in result['cases'].items(): print(name, json.dumps(c['valuation']), 'funding gap',c['max_funding_gap'])

if __name__=='__main__': main()
