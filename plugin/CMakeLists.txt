cmake_minimum_required(VERSION 3.22)

# ── Jsplit — offline stem-splitter plugin ──────────────────────────────────
# Architecture: the plugin is a THIN FRONT-END. It does NOT run the neural
# network in the audio thread (HTDemucs / RoFormer cannot run in real time).
# Instead it collects your choices (file, quality, stems) and drives the same
# Python engine the CLI uses, then writes the stems to disk for you to drag
# back into your DAW. See BUILD.md and Source/SeparationBridge.h.
#
# This builds a Standalone app AND a VST3. JUCE is fetched automatically.

project(Jsplit VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
FetchContent_Declare(
    JUCE
    GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
    GIT_TAG        7.0.12          # bump to a newer tag if you like
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(JUCE)

juce_add_plugin(Jsplit
    PRODUCT_NAME              "Jsplit"
    COMPANY_NAME             "Jsplit"
    PLUGIN_MANUFACTURER_CODE  Jspl
    PLUGIN_CODE               Jsp1
    FORMATS                   VST3 Standalone
    IS_SYNTH                  FALSE
    NEEDS_MIDI_INPUT          FALSE
    NEEDS_MIDI_OUTPUT         FALSE
    IS_MIDI_EFFECT            FALSE
    COPY_PLUGIN_AFTER_BUILD   TRUE
    VST3_CATEGORIES           "Fx" "Tools"
)

target_sources(Jsplit PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp
    Source/SeparationBridge.cpp
)

# our sources use #include <JuceHeader.h>, which must be generated explicitly
juce_generate_juce_header(Jsplit)

target_compile_definitions(Jsplit PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0
)

target_link_libraries(Jsplit PRIVATE
    juce::juce_audio_utils
    juce::juce_gui_extra
    PUBLIC
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)
