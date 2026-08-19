#pragma once
#include <JuceHeader.h>

/**
    Runs the Jsplit Python engine (scripts/split.py) as a child process on a
    background thread, streaming its stdout back line-by-line. This is the bridge
    between the C++ plugin and the actual neural separation.

    Contract with the Python side (scripts/split.py):
        <python> <home>/scripts/split.py -i <in> -o <out> -q <quality>
                 --stems <csv> --no-metrics
    On success the script prints a line:  JSPLIT_OUTPUT_DIR=<folder>
    which we parse to know where the stems landed.

    Callbacks fire on the BACKGROUND thread — the editor marshals them to the
    message thread before touching any UI.
*/
class SeparationBridge : private juce::Thread
{
public:
    struct Config
    {
        juce::String pythonPath;   // e.g. .../.venv/Scripts/python.exe
        juce::File   engineHome;   // repo root containing scripts/split.py
        juce::File   inputFile;
        juce::File   outputDir;
        juce::String quality;      // fast | balanced | full | max
        juce::String stemsCsv;     // "vocals,drums,bass,other"
    };

    std::function<void (const juce::String& line)> onLine;
    std::function<void (bool ok, const juce::File& outputFolder)> onFinished;

    SeparationBridge() : juce::Thread ("JsplitBridge") {}
    ~SeparationBridge() override { cancel(); }

    // Validate config, return an error string (empty = OK) before launching.
    juce::String validate (const Config&) const;

    void start (const Config& c) { cfg = c; startThread(); }
    void cancel();
    bool isRunning() const { return isThreadRunning(); }

private:
    void run() override;

    Config cfg;
    juce::CriticalSection procLock;
    std::unique_ptr<juce::ChildProcess> proc;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SeparationBridge)
};
