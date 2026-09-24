[app]
title = Gerador de Relatorios SC
project_dir = .
input_file = gerador_sc/__main__.py
exec_directory = dist

[python]
python_path =
packages = Nuitka==4.1.1

[qt]
modules = Core,Gui,Widgets

[nuitka]
mode = standalone
extra_args = --quiet --noinclude-qt-translations --include-data-dir=geodados=geodados --include-package=gerador_sc
