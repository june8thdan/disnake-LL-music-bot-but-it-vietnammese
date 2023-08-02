#!/bin/bash

rm -f poetry.lock && rm -f pyproject.toml && rm -rf .upm
pip3 uninstall poetry -y

if [ "${SOURCE_AUTO_UPDATE,,}" == "true" ]; then
  bash quick_update.sh
fi

if [ ! -d "venv" ] || [ ! -f "./venv/bin/requirements.txt" ] || [ ! "$REPL_SLUG-$REPL_OWNER" == "$(cat ./venv/.deployed)" ]; then
  rm -rf venv && rm -rf .config && rm -rf .cache && rm Lavalink.jar && rm -rf local_database
  rm -f poetry.lock && rm -f pyproject.toml
  echo -e "\n####################################" \
          "\n### Inicializando virtual_env... ###" \
          "\n####################################\n"
  python3 -m venv venv
  . venv/bin/activate
  python3 -m pip install -U pip
  echo -e "\n###################################################" \
          "\n### Instalando dependências...                  ###" \
          "\n### (Esse processo pode demorar até 3 minutos). ###" \
          "\n###################################################\n"
  pip3 install -U -r requirements.txt --no-cache-dir
  cp -r requirements.txt ./venv/bin/requirements.txt
  echo -n "$REPL_SLUG-$REPL_OWNER" > ./venv/.deployed

elif ! cmp --silent -- "./requirements.txt" "./venv/bin/requirements.txt"; then
  echo -e "\n##############################################" \
          "\n### Instalando/Atualizando dependências... ###" \
          "\n##############################################\n"
  . venv/bin/activate
  pip3 install -U -r requirements.txt --no-cache-dir
  cp -r requirements.txt ./venv/bin/requirements.txt

else
  . venv/bin/activate

fi

python3 main.py
