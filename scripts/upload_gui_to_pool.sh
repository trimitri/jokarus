#!/bin/bash
rsync -r -v --chmod=755 --delete ../pyodine/gui/ gutsch@pool13.physik.hu-berlin.de:public_html/pyodine/gui/
