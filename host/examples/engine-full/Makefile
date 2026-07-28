# Enigma engine example (input side) - build and run the demo.
#
#   make install    install the library (with the audio + display extras)
#   make gen        regenerate generated/ code from the configs
#   make demo       run the display server + the panel app (reads boards), with audio
#   make display    run just the display server
#   make app        run just the panel app (no audio)
#   make app-audio  run just the panel app, with audio
#   make help       show this list
#
# Point your browser at http://localhost:$(PORT)/ once it is running.

PORT ?= 8080
URL  := http://localhost:$(PORT)
PY   ?= python3

GEN_CONTROLS := generated/controls.py
GEN_DEVICES  := generated/devices.py
GEN_AUDIO    := generated/audio_events.py

.DEFAULT_GOAL := help
.PHONY: help install gen demo display app app-audio clean

help:
	@echo ""
	@echo "Enigma engine example (input side)"
	@echo "----------------------------------"
	@echo "  make install    install the library + [audio,display] extras (run once)"
	@echo "  make gen        regenerate generated/ code from configs/"
	@echo "  make demo       run display server + panel app (reads boards), with audio"
	@echo "  make display    run just the display server"
	@echo "  make app        run just the panel app (no audio)"
	@echo "  make app-audio  run just the panel app, with audio"
	@echo "  make clean      remove __pycache__ directories"
	@echo ""
	@echo "  Then open the display in your browser:  $(URL)/"
	@echo "  No boards? See ../engine-sw for an interactive controls page."
	@echo ""

install:
	$(PY) -m pip install -e "../..[audio,display]"

$(GEN_CONTROLS): configs/control_mappings.json configs/EngineAnalog.json configs/EngineSwitches.json configs/EngineDial.json
	$(PY) -m enigma.tools.generate_controls --config-dir configs --output $@ --docs generated/controls.txt

$(GEN_DEVICES): configs/device_mappings.json configs/PortEngineSpec.json
	$(PY) -m enigma.tools.generate_devices --config-dir configs --output $@ --docs generated/devices.txt

$(GEN_AUDIO): configs/audio_library.json configs/audio_classes.json
	$(PY) -m enigma.tools.generate_audio --config-dir configs --output $@ --docs generated/audio.txt

gen: $(GEN_CONTROLS) $(GEN_DEVICES) $(GEN_AUDIO)

# Display server in the background, app in the foreground; the trap reaps the
# server when the app exits (Ctrl-C).
demo: gen
	@$(PY) display/server.py --port $(PORT) --content display/content & \
	SRV=$$!; trap "kill $$SRV 2>/dev/null" EXIT INT TERM; sleep 1; \
	printf '\n============================================================\n'; \
	printf '  Open the display in your browser:  %s/\n' "$(URL)"; \
	printf '============================================================\n\n'; \
	$(PY) application/engine_panel.py --audio

display:
	@echo "Serving display at $(URL)/  (Ctrl-C to stop)"
	$(PY) display/server.py --port $(PORT) --content display/content

app: $(GEN_CONTROLS) $(GEN_DEVICES)
	$(PY) application/engine_panel.py

app-audio: $(GEN_CONTROLS) $(GEN_DEVICES) $(GEN_AUDIO)
	$(PY) application/engine_panel.py --audio

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
