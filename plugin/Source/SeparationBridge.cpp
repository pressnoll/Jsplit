#include "SeparationBridge.h"

juce::String SeparationBridge::validate (const Config& c) const
{
    if (c.inputFile == juce::File() || ! c.inputFile.existsAsFile())
        return "Choose a valid audio file first.";

    auto script = c.engineHome.getChildFile ("scripts/split.py");
    if (! script.existsAsFile())
        return "Can't find the engine (scripts/split.py). Set the engine folder in Settings.";

    if (c.pythonPath.isEmpty())
        return "No Python interpreter set. Point Jsplit at your .venv python in Settings.";

    if (c.stemsCsv.trim().isEmpty())
        return "Select at least one stem to export.";

    return {};
}

void SeparationBridge::cancel()
{
    {
        const juce::ScopedLock sl (procLock);
        if (proc != nullptr && proc->isRunning())
            proc->kill();
    }
    stopThread (4000);
}

void SeparationBridge::run()
{
    auto script = cfg.engineHome.getChildFile ("scripts/split.py");

    juce::StringArray args;
    args.add (cfg.pythonPath);
    args.add ("-u");                       // unbuffered -> progress streams live
    args.add (script.getFullPathName());
    args.add ("-i"); args.add (cfg.inputFile.getFullPathName());
    args.add ("-o"); args.add (cfg.outputDir.getFullPathName());
    args.add ("-q"); args.add (cfg.quality);
    args.add ("--stems"); args.add (cfg.stemsCsv);
    args.add ("--no-metrics");             // the GUI/CLI show metrics; keep the plugin snappy

    {
        const juce::ScopedLock sl (procLock);
        proc = std::make_unique<juce::ChildProcess>();
        // Run from the repo root so `import src...` resolves.
        // (ChildProcess has no cwd arg; split.py adds the repo to sys.path itself,
        //  and we pass absolute paths, so cwd is not required.)
        if (! proc->start (args, juce::ChildProcess::wantStdOut | juce::ChildProcess::wantStdErr))
        {
            if (onLine) onLine ("ERROR: could not launch Python. Check the interpreter path.");
            if (onFinished) onFinished (false, {});
            return;
        }
    }

    juce::File resolvedOut = cfg.outputDir.getChildFile (cfg.inputFile.getFileNameWithoutExtension());
    juce::String carry;

    // Stream output as it arrives.
    char chunk[2048];
    while (! threadShouldExit())
    {
        int n = 0;
        {
            const juce::ScopedLock sl (procLock);
            if (proc == nullptr) break;
            if (! proc->isRunning() && proc->getNumBytesAvailableToRead() <= 0)
                break;
            n = proc->readProcessOutput (chunk, (int) sizeof (chunk));
        }

        if (n > 0)
        {
            carry += juce::String::fromUTF8 (chunk, n);
            for (;;)
            {
                auto nl = carry.indexOfChar ('\n');
                if (nl < 0) break;
                auto line = carry.substring (0, nl).trimEnd();
                carry = carry.substring (nl + 1);

                if (line.startsWith ("JSPLIT_OUTPUT_DIR="))
                    resolvedOut = juce::File (line.fromFirstOccurrenceOf ("JSPLIT_OUTPUT_DIR=", false, false).trim());
                else if (line.isNotEmpty() && onLine)
                    onLine (line);
            }
        }
        else
        {
            wait (50);
        }
    }

    if (carry.trim().isNotEmpty() && onLine)
        onLine (carry.trim());

    bool ok = false;
    {
        const juce::ScopedLock sl (procLock);
        if (proc != nullptr)
        {
            proc->waitForProcessToFinish (10000);
            ok = (proc->getExitCode() == 0);
        }
    }

    if (onFinished)
        onFinished (ok, resolvedOut);
}
