# Enigma engine example (software side) - build and run the demo.
#
#   make install    install the library (with the audio + display extras)
#   make gen        regenerate generated/ code from the configs
#   make demo       run the display server + the app (serves the panel, with audio)
#   make display    run just the display server
#   make app        run just the app (no audio)
#   make app-audio  run just the app, with audio
#   make help       show this list
#
# The app serves the simulated panel on http://localhost:8090/; the display is at
# http://localhost:$(PORT)/.

PORT ?= 8080
URL  := http://localhost:$(PORT)
PY   ?= python3

GEN_DEVICES := generated/devices.py
GEN_AUDIO   := generated/audio_events.py

.DEFAULT_GOAL := help
.PHONY: help install gen demo display app app-audio clean

help:
	@echo ""
	@echo "Enigma engine example (software side)"
	@echo "-------------------------------------"
	@echo "  make install     install the library + [audio,display] extras (run once)"
	@echo "  make gen         regenerate generated/ code from configs/"
	@echo "  make demo        run display server + app (serves the panel, with audio)"
	@echo "  make display     run just the display server"
	@echo "  make app         run just the app (no audio)"
	@echo "  make app-audio   run just the app, with audio"
	@echo "  make clean       remove __pycache__ directories"
	@echo ""
	@echo "  Display:  $(URL)/    Panel (served by the app):  http://localhost:8090/"
	@echo ""

install:
	$(PY) -m pip install -e "../..[audio,display]"

$(GEN_DEVICES): configs/device_mappings.json configs/PortEngineSpec.json
	$(PY) -m enigma.tools.generate_devices --config-dir configs --output $@ --docs generated/devices.txt

$(GEN_AUDIO): configs/audio_library.json configs/audio_classes.json
	$(PY) -m enigma.tools.generate_audio --config-dir configs --output $@ --docs generated/audio.txt

gen: $(GEN_DEVICES) $(GEN_AUDIO)

# Display server in the background, app in the foreground; the trap reaps the
# server when the app exits (Ctrl-C). The app serves the panel on port 8090.
demo: $(GEN_DEVICES) $(GEN_AUDIO)
	@$(PY) display/server.py --port $(PORT) --content display/content & \
	SRV=$$!; \
	trap "kill $$SRV 2>/dev/null" EXIT INT TERM; \
	sleep 1; \
	printf '\n============================================================\n'; \
	printf '  Display:  %s/\n' "$(URL)"; \
	printf '  Panel:    http://localhost:8090/   (served by the app)\n'; \
	printf '============================================================\n\n'; \
	$(PY) application/example_app.py --audio

display:
	@echo "Serving display at $(URL)/  (Ctrl-C to stop)"
	$(PY) display/server.py --port $(PORT) --content display/content

app: $(GEN_DEVICES)
	$(PY) application/example_app.py

app-audio: $(GEN_DEVICES) $(GEN_AUDIO)
	$(PY) application/example_app.py --audio

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
