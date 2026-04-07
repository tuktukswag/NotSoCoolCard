import sys, codecs
with codecs.open('debug_mox_probe_output.txt', 'r', 'utf-16') as f:
    sys.stdout.write(f.read())
