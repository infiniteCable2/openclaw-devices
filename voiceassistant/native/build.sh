#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
mkdir -p build
g++ -std=c++17 -O2 -fPIC -shared native/webrtc_apm.cc \
  -o build/libopenclaw-apm.so \
  $(pkg-config --cflags --libs webrtc-audio-processing-1)
