#!/bin/bash
clear
printf "\n\n"
rm /data/data/com.termux/files/usr/bin/aliens_eye &>/dev/null
cp aliens_eye.py /data/data/com.termux/files/usr/bin/aliens_eye
chmod +x /data/data/com.termux/files/usr/bin/aliens_eye
printf "\n\ninstalled successfully!\n"
