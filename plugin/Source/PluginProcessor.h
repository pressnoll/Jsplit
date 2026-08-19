#pragma once
#include <JuceHeader.h>

/**
    Jsplit — offline stem splitter (processor).

    IMPORTANT ARCHITECTURE NOTE
    ---------------------------
    Separation quality is the whole point of this project, so we run the real
    models (HTDemucs / Mel-Band RoFormer). Those cannot run inside a real-time
    audio callback. So this plugin is deliberately OFFLINE:

        drop the audio  ->  choose the stems  ->  Generate  ->  export to disk

    processBlock() therefore does NOT separate anything. It just passes the main
    input through to the main output for monitoring and clears the (optional)
    stem buses. The heavy lifting is done by the Python engine, launched from the
    editor via SeparationBridge. Rendered stems are written to a folder you then
    drag back into your DAW.

    The extra stereo output buses (Vocals/Drums/Bass/Other/Guitar/Piano) are
    declared so a future version can stream already-rendered stems out to
    separate tracks; today they stay silent.
*/
class JsplitAudioProcessor : public juce::AudioProcessor
{
public:
    JsplitAudioProcessor();
    ~JsplitAudioProcessor() override = default;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
    bool isBusesLayoutSupported (const BusesLayout&) const override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return "Jsplit"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    // ── Persisted user choices (edited from the editor) ────────────────────
    // Stored in a thread-safe ValueTree so state survives session reloads.
    juce::ValueTree& state() { return settings; }

    // Best-effort auto-detection of the Python engine on first launch.
    void autoDetectEngine();

private:
    juce::ValueTree settings { "JsplitSettings" };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (JsplitAudioProcessor)
};
