# Counts CUDA fatbin entries by (kind, sm arch) in a binary: kind 1 = PTX, 2 = SASS (ELF cubin).
import struct, sys, collections
data = open(sys.argv[1], "rb").read()
MAGIC = struct.pack("<I", 0xBA55ED50)
counts = collections.Counter()
pos = 0
while (pos := data.find(MAGIC, pos)) != -1:
    _, version, hsize, fsize = struct.unpack_from("<IHHQ", data, pos)
    if version != 1 or hsize != 16:
        pos += 4; continue
    e, end = pos + hsize, pos + hsize + fsize
    while e + 32 <= end:
        kind, _, ehsize, psize = struct.unpack_from("<HHIQ", data, e)
        arch = struct.unpack_from("<I", data, e + 28)[0]
        if kind not in (1, 2) or ehsize < 32 or psize == 0:
            break
        counts[("PTX" if kind == 1 else "SASS", arch)] += 1
        e += ehsize + psize
    pos = end
for (kind, arch), n in sorted(counts.items(), key=lambda x: (x[0][0], x[0][1])):
    print(f"{kind} sm_{arch}: {n}")
