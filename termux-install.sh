#!/bin/bash
clear
printf "\n\n"
rm /data/data/com.termux/files/usr/bin/aliens_eye &>/dev/null
rm /data/data/com.termux/files/usr/bin/sites.json &>/dev/null
cp aliens_eye.py /data/data/com.termux/files/usr/bin/aliens_eye
cp sites.json /data/data/com.termux/files/usr/bin/sites.json

chmod +x /data/data/com.termux/files/usr/bin/aliens_eye
printf "\n\ninstalled successfully!\n"
