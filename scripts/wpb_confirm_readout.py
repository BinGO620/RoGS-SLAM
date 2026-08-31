import math
raw = """vanilla|pt1|0|76.9205 vanilla|pt1|1|55.6298 vanilla|pt1|2|57.1007
vanilla|pt2|0|45.151 vanilla|pt2|1|43.4505 vanilla|pt2|2|47.499
vanilla|mv_no_box2|0|6.882 vanilla|mv_no_box2|1|5.8797 vanilla|mv_no_box2|2|34.1626
vanilla|balloon2|0|23.3916 vanilla|balloon2|1|24.4014 vanilla|balloon2|2|24.5038
flowmask|pt1|0|62.1057 flowmask|pt1|1|39.7609 flowmask|pt1|2|52.3645
flowmask|pt2|0|61.8435 flowmask|pt2|1|39.669 flowmask|pt2|2|51.6942
flowmask|mv_no_box2|0|6.6086 flowmask|mv_no_box2|1|5.7434 flowmask|mv_no_box2|2|6.351
flowmask|balloon2|0|31.0985 flowmask|balloon2|1|11.3652 flowmask|balloon2|2|27.4431
MRCS|pt1|0|41.5365 MRCS|pt1|1|37.4913 MRCS|pt1|2|36.5083
MRCS|pt2|0|9.4044 MRCS|pt2|1|8.7752 MRCS|pt2|2|9.0904
MRCS|mv_no_box2|0|4.9031 MRCS|mv_no_box2|1|4.7107 MRCS|mv_no_box2|2|5.2939
MRCS|balloon2|0|14.2342 MRCS|balloon2|1|10.9212 MRCS|balloon2|2|10.5401"""
D={}
for tok in raw.split():
    a,s,sd,v=tok.split('|'); D[(a,s,int(sd))]=float(v)
DELTA=0.20; SEQ1=['pt1','pt2']; SEQ2=['mv_no_box2','balloon2']
mean=lambda x: sum(x)/len(x)
print("="*74)
print("WP-B CONFIRM 36-run — held-out 三臂 (ATE cm, mean ± half-range, 3 seed)")
print("="*74)
print(f"{'seq':<12}{'vanilla':>19}{'flow-mask':>19}{'MRCS':>19}")
for s in SEQ1+SEQ2:
    row=f"{s:<12}"
    for a in ('vanilla','flowmask','MRCS'):
        v=[D[(a,s,i)] for i in range(3)]
        row+=f"{mean(v):>11.2f}±{(max(v)-min(v))/2:<7.2f}"
    print(row+(" (1)" if s in SEQ1 else " (2)"))
print("\n"+"="*74)
print("PRIMARY: paired log(ATE_flowmask / ATE_MRCS), delta=0.20  [+ = MRCS better]")
print("="*74)
verdict={}
for s in SEQ1+SEQ2:
    lr=[math.log(D[('flowmask',s,i)]/D[('MRCS',s,i)]) for i in range(3)]
    m=mean(lr); pos=all(x>0 for x in lr); neg=all(x<0 for x in lr)
    if m>DELTA and pos: br="B1 MRCS-better"
    elif m<-DELTA and neg: br="B3 naive-better"
    elif -DELTA<=m<=DELTA: br="B2 no-difference"
    else: br="B4 indeterminate"
    verdict[s]=br
    print(f"{s:<12} seeds {lr[0]:+.3f} {lr[1]:+.3f} {lr[2]:+.3f} | mean {m:+.3f} "
          f"= {math.exp(m):.2f}x | 3/3 same-sign {'YES' if pos or neg else 'NO'} -> {br}")
print()
print(f"held-out(1) PRIMARY : pt1={verdict['pt1']} | pt2={verdict['pt2']}  => "
      f"{'2/2 CONSISTENT' if verdict['pt1']==verdict['pt2'] else 'SPLIT'}")
print(f"held-out(2) support : mv_no_box2={verdict['mv_no_box2']} | balloon2={verdict['balloon2']}")
print("\n"+"="*74)
print("SIDE: log(ATE_vanilla / ATE_flowmask)  [+ = flow-mask beats vanilla]")
print("="*74)
for s in SEQ1+SEQ2:
    lr=[math.log(D[('vanilla',s,i)]/D[('flowmask',s,i)]) for i in range(3)]
    m=mean(lr); pos=all(x>0 for x in lr); neg=all(x<0 for x in lr)
    print(f"{s:<12} mean {m:+.3f} = {math.exp(m):.2f}x | 3/3 same-sign {'YES' if pos or neg else 'NO'}")
print("\n"+"="*74)
print("SIDE: log(ATE_vanilla / ATE_MRCS)  [+ = MRCS beats vanilla]")
print("="*74)
for s in SEQ1+SEQ2:
    lr=[math.log(D[('vanilla',s,i)]/D[('MRCS',s,i)]) for i in range(3)]
    m=mean(lr); pos=all(x>0 for x in lr)
    print(f"{s:<12} mean {m:+.3f} = {math.exp(m):.2f}x | 3/3 same-sign {'YES' if pos else 'NO'}")
