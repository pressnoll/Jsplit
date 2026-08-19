#pragma once
#include <JuceHeader.h>
#include "PluginProcessor.h"
#include "SeparationBridge.h"

/**
    Jsplit editor — the plugin's face.

        1 · Load a song
        2 · Pick a quality tier
        3 · Tick the stems you want
        4 · Generate  ->  stems are written to the export folder
        5 · Open folder  ->  drag them onto tracks in your DAW

    A small Settings strip lets you point the plugin at the Python interpreter
    and the engine repo (auto-detected on first launch).
*/
class JsplitAudioProcessorEditor : public juce::AudioProcessorEditor,
                                   private juce::Timer
{
public:
    explicit JsplitAudioProcessorEditor (JsplitAudioProcessor&);
    ~JsplitAudioProcessorEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    void rebuildStemToggles();
    void onGenerate();
    void appendStatus (const juce::String& line);
    void setBusy (bool busy);
    void pushSelectionToState();
    void timerCallback() override;   // drives the busy bar animation

    JsplitAudioProcessor& proc;
    SeparationBridge bridge;

    // header
    juce::Label title, subtitle;

    // 1 · song
    juce::TextButton loadButton { "Load audio…" };
    juce::Label      fileLabel;

    // 2 · quality
    juce::ComboBox   qualityBox;
    juce::Label      qualityHint;

    // 3 · stems
    juce::Label                                    stemsHeader;
    juce::OwnedArray<juce::ToggleButton>           stemToggles;

    // 4 · export
    juce::Label      outDirLabel;
    juce::TextButton changeOutButton { "Change…" };

    // action
    juce::TextButton generateButton { "Generate stems" };
    juce::TextButton openFolderButton { "Open export folder" };
    juce::ProgressBar progressBar { progress };
    double progress { 0.0 };

    // status log
    juce::TextEditor statusLog;

    // settings strip
    juce::Label      pyLabel, homeLabel;
    juce::TextButton pyBrowse { "Python…" }, homeBrowse { "Engine…" };

    juce::File lastOutputFolder;
    std::unique_ptr<juce::FileChooser> chooser;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (JsplitAudioProcessorEditor)
};
