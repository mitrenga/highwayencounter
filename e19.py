import sys, statistics; sys.path.insert(0,'/tmp/claude-1000/-home-libmit-sw-highwayencounter/cfd37d3b-1d0a-4f66-bd52-8d77cb0037a5/scratchpad')
from steplib import Stepper
from skoolkit.simutils import T
st = Stepper(); sim = st.s.simulator
ts=[sim.registers[T]]
for i in range(600):
    st.step(('1',) if (i//30)%2==0 else ('O',) if (i//30)%4==1 else ())
    ts.append(sim.registers[T])
d=[ts[i+1]-ts[i] for i in range(len(ts)-1)]
fd = sim.frame_duration
print('T na krok: min %d max %d median %d prumer %.0f' % (min(d), max(d), statistics.median(d), statistics.mean(d)))
print('snimku na krok: %.4f  (krok = %.3f Hz)' % (statistics.mean(d)/fd, 3500000/statistics.mean(d)))
import collections
print(collections.Counter([round(x/1000) for x in d]).most_common(12))
