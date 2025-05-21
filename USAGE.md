# Project Structure
```
$ tree ~
downloads/
├── bin.tar.gz
├── bin/
├── Foam-Agent/
│   ├── database/
│   ├── environment.yml
│   ├── foambench_main.py
│   ├── LICENSE
│   ├── output/
│   ├── overview.png
│   ├── prompt.txt
│   ├── README.md
│   ├── runs/
│   ├── src/
│   ├── USAGE.md
│   └── user_requirement.txt
├── Miniconda3-latest-Linux-x86_64.sh
├── OpenFOAM-v2206/
│   ├── Allwmake
│   ├── applications/
│   ├── bin/
│   ├── build/
│   ├── CONTRIBUTORS.md
│   ├── COPYING
│   ├── doc/
│   ├── etc/
│   ├── META-INFO/
│   ├── modules/
│   ├── platforms/
│   ├── README.md
│   ├── src/
│   ├── tutorials/
│   └── wmake/
├── OpenFOAM-v2206.tgz
├── TianLuo25.1.0-x86_64_202504291122_Linux/
│   ├── bin/
│   ├── Dependencies/
│   ├── Docs/
│   ├── Ext/
│   ├── lib/
│   ├── Mod/
│   └── setup.sh
└── TianLuo25.1.0-x86_64_202504291122_Linux.tar.bz2

3 directories, 17 files
```

# Download files
```bash
# on your computer
rsync -avz  --progress ./Downloads/OpenFOAM-v2206.tgz cfd:~/downloads
rsync -avz  --progress ./Downloads/TianLuo25.1.0-x86_64_202504291122_Linux.tar.bz2 cfd:~/downloads
rsync -avz  --progress ./Downloads/bin.tar.gz cfd:~/downloads

# server
cd downloads
tar xvf TianLuo25.1.0-x86_64_202504291122_Linux.tar.bz2
tar xvf OpenFOAM-v2206.tgz
tar xvf bin.tar.gz
mv bin TianLuo25.1.0-x86_64_202504291122_Linux/bin/Tools/scripts/__pycache__/meshTool/
```

# Add solver_env.sh
```bash
cat << EOF >> ~/downloads/TianLuo25.1.0-x86_64_202504291122_Linux/bin/Tools/scripts/__pycache__/meshTool/solver_env.sh
#! /bin/bash
export WM_PROJECT_DIR="/home/$USER/downloads/TianLuo25.1.0-x86_64_202504291122_Linux/bin/Tools/scripts/__pycache__/meshTool"
export OPAL_PREFIX=$WM_PROJECT_DIR/ThirdParty/linux64Gcc/openmpi-4.1.2
export PATH=$WM_PROJECT_DIR/linux64GccDPInt32Opt/bin:$PATH
export PATH=$WM_PROJECT_DIR/ThirdParty/linux64Gcc/openmpi-4.1.2/bin:$PATH
export LD_LIBRARY_PATH=$WM_PROJECT_DIR/linux64GccDPInt32Opt/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=$WM_PROJECT_DIR/linux64GccDPInt32Opt/lib/openmpi-4.1.2:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=$WM_PROJECT_DIR/ThirdParty/linux64GccDPInt32/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=$WM_PROJECT_DIR/ThirdParty/linux64GccDPInt32/lib/openmpi-4.1.2:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=$WM_PROJECT_DIR/ThirdParty/linux64Gcc/openmpi-4.1.2/lib:$LD_LIBRARY_PATH
EOF
```

# Foam-Agent
```bash
# set up proxy network
export https_proxy=your-proxy-url:port http_proxy=http://your-proxy-url:port all_proxy=socks5://your-proxy-url:port
git clone https://github.com/stepbystepcode/Foam-Agent.git

# you need install conda first
# create python env
conda env create -f environment.yml
conda activate openfoamAgent

# set up your key
export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# export OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# compile OpenFOAM-v2206
cd ~/downloads/OpenFOAM-v2206
source ./etc/bashrc

# install deps
sudo apt install m4 flex openmpi ncurses

# set muti-threads compile
export WM_NCOMPPROCS=$(nproc)

# compile (A long time)
./Allwmake

# install ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull nomic-embed-text
nohup ollama serve &

# change your prompt
cd ~/downloads/Foam-Agent
vim prompt.txt
python3 foambench_main.py --openfoam_path ~/downloads/OpenFOAM-v2206 --output ~/downloads/Foam-Agent/output --prompt_path ~/downloads/Foam-Agent/prompt.txt
cd output

# source Tianluo env
cd ~/downloads/TianLuo25.1.0-x86_64_202504291122_Linux/bin/Tools/scripts/__pycache__/meshTool/
source ./solver_env.sh
ln -s ~/downloads/TianLuo25.1.0-x86_64_202504291122_Linux/bin/Tools/scripts/__pycache__/meshTool/bin/tools/RunFunctions ~/downloads/TianLuo25.1.0-x86_64_202504291122_Linux/bin/Tools/scripts/__pycache__/meshTool/RunFunctions
cd ~/downloads/Foam-Agent/output
./Allrun
```
