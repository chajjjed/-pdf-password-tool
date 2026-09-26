[app]
title = PDF Password Tool
package.name = pdfpasswordtool
package.domain = org.yourshop

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 1.0



requirements = python3==3.11.8,hostpython3==3.11.8,kivy,pypdf
orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png

android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE

android.api = 33
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a,armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
