#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

LIB = os.path.dirname(os.path.abspath(__file__))

def rp(html_path, new_content):
    with open(html_path, "r", encoding="utf-8") as f:
        c = f.read()
    s = c.find("<main id=\"main\">") 
    # Try alternate
    if s < 0: s = c.find("<main id='main'>")
    e = c.find("</main>")
    if s < 0 or e < 0:
        print("ERR: no main in " + html_path)
        return False
    nc = c[:s] + "<main id=\"main\">

" + new_content + "

</main>" + c[e+7:]
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(nc)
    print("DONE: " + os.path.basename(html_path) + " (" + str(len(nc)) + " chars)")
    return True
