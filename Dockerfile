# Dockerfile
FROM python:3.11.9-slim-bookworm

RUN pip install --no-cache-dir \
    jax==0.4.38 jaxlib==0.4.38 numpyro==0.16.2 \
    numpy==1.26.4 scipy==1.14.1 nuitka==2.6.9

COPY arkhe_inference_v3.1.py /app/
WORKDIR /app

# Compile to Windows PE (cross-compile via wine or native on Windows)
# For Linux build, we use `--standalone` and `--onefile` for Windows target.
# In this environment, we assume native Windows build with Nuitka.
RUN nuitka --standalone --onefile --windows-console-mode=disable \
    --lto=yes --no-pyi-file --output-dir=build arkhe_inference_v3.1.py

RUN sha256sum build/arkhe_inference_v3.1.exe > arkhe_sha256.txt
