#include "PluginProcessor.h"
#include "PluginEditor.h"

namespace
{
    // Default keys stored in the settings ValueTree.
    const juce::Identifier kInputFile   { "inputFile" };
    const juce::Identifier kOutputDir   { "outputDir" };
    const juce::Identifier kQuality     { "quality" };
    const juce::Identifier kStems       { "stems" };        // comma-separated
    const juce::Identifier kPythonPath  { "pythonPath" };
    const juce::Identifier kEngineHome  { "engineHome" };   // repo root (has scripts/split.py)
}

JsplitAudioProcessor::JsplitAudioProcessor()
    : AudioProcessor (BusesProperties()
        .withInput  ("Input",  juce::AudioChannelSet::stereo(), true)
        .withOutput ("Main",   juce::AudioChannelSet::stereo(), true)
        // Optional per-stem outputs for a future live-routing mode (silent today):
        .withOutput ("Vocals", juce::AudioChannelSet::stereo(), false)
        .withOutput ("Drums",  juce::AudioChannelSet::stereo(), false)
        .withOutput ("Bass",   juce::AudioChannelSet::stereo(), false)
        .withOutput ("Other",  juce::AudioChannelSet::stereo(), false)
        .withOutput ("Guitar", juce::AudioChannelSet::stereo(), false)
        .withOutput ("Piano",  juce::AudioChannelSet::stereo(), false))
{
    // Sensible defaults.
    settings.setProperty (kQuality,   "full", nullptr);
    settings.setProperty (kStems,     "vocals,drums,bass,other,guitar,piano", nullptr);
    settings.setProperty (kOutputDir,
        juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
            .getChildFile ("Jsplit Stems").getFullPathName(), nullptr);
    autoDetectEngine();
}

void JsplitAudioProcessor::autoDetectEngine()
{
    // 0) config file written by the installer wins for a fresh install.
    //    Checked machine-wide first (C:\ProgramData\Jsplit), then per-user.
    juce::Array<juce::File> cfgCandidates {
        juce::File::getSpecialLocation (juce::File::commonApplicationDataDirectory)
            .getChildFile ("Jsplit").getChildFile ("jsplit.config"),
        juce::File::getSpecialLocation (juce::File::userApplicationDataDirectory)
            .getChildFile ("Jsplit").getChildFile ("jsplit.config"),
    };
    for (auto& cfgFile : cfgCandidates)
    {
        if (! cfgFile.existsAsFile()) continue;
        auto lines = juce::StringArray::fromLines (cfgFile.loadFileAsString());
        for (auto& ln : lines)
        {
            auto key = ln.upToFirstOccurrenceOf ("=", false, false).trim();
            auto val = ln.fromFirstOccurrenceOf ("=", false, false).trim();
            if (val.isEmpty()) continue;
            if (key == "python" && ! settings.hasProperty (kPythonPath))
                settings.setProperty (kPythonPath, val, nullptr);
            if (key == "home"   && ! settings.hasProperty (kEngineHome))
                settings.setProperty (kEngineHome, val, nullptr);
        }
    }

    // 1) explicit environment overrides
    auto envPy   = juce::SystemStats::getEnvironmentVariable ("JSPLIT_PYTHON", {});
    auto envHome = juce::SystemStats::getEnvironmentVariable ("JSPLIT_HOME", {});
    if (envHome.isNotEmpty() && ! settings.hasProperty (kEngineHome)) settings.setProperty (kEngineHome, envHome, nullptr);
    if (envPy.isNotEmpty()   && ! settings.hasProperty (kPythonPath)) settings.setProperty (kPythonPath, envPy, nullptr);

    // 2) walk up from the plugin binary to find a repo that has scripts/split.py
    if (! settings.hasProperty (kEngineHome))
    {
        auto dir = juce::File::getSpecialLocation (juce::File::currentApplicationFile);
        for (int i = 0; i < 8 && dir.exists(); ++i)
        {
            if (dir.getChildFile ("scripts/split.py").existsAsFile())
            {
                settings.setProperty (kEngineHome, dir.getFullPathName(), nullptr);
                break;
            }
            dir = dir.getParentDirectory();
        }
    }

    // 3) prefer the repo's virtualenv python if present
    if (! settings.hasProperty (kPythonPath) && settings.hasProperty (kEngineHome))
    {
        juce::File home (settings[kEngineHome].toString());
       #if JUCE_WINDOWS
        auto venv = home.getChildFile (".venv/Scripts/python.exe");
       #else
        auto venv = home.getChildFile (".venv/bin/python");
       #endif
        settings.setProperty (kPythonPath,
            venv.existsAsFile() ? venv.getFullPathName() : juce::String ("python"), nullptr);
    }
}

void JsplitAudioProcessor::prepareToPlay (double, int) {}

bool JsplitAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    // Main in/out must be stereo (or mono); stem buses are optional and may be disabled.
    const auto mainOut = layouts.getMainOutputChannelSet();
    if (mainOut != juce::AudioChannelSet::stereo() && mainOut != juce::AudioChannelSet::mono())
        return false;
    return true;
}

void JsplitAudioProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;

    // Offline design: pass the main input through for monitoring, silence the
    // optional stem buses. No neural work happens here (see header note).
    for (int bus = 1; bus < getBusCount (false); ++bus)
        if (auto* b = getBus (false, bus))
            if (b->isEnabled())
                for (int ch = 0; ch < b->getNumberOfChannels(); ++ch)
                    buffer.clear (b->getChannelIndexInProcessBlockBuffer (ch), 0, buffer.getNumSamples());
}

juce::AudioProcessorEditor* JsplitAudioProcessor::createEditor()
{
    return new JsplitAudioProcessorEditor (*this);
}

void JsplitAudioProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    if (auto xml = settings.createXml())
        copyXmlToBinary (*xml, destData);
}

void JsplitAudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    if (auto xml = getXmlFromBinary (data, sizeInBytes))
    {
        auto restored = juce::ValueTree::fromXml (*xml);
        if (restored.isValid())
            settings.copyPropertiesAndChildrenFrom (restored, nullptr);
    }
    // fill in anything missing (e.g. new install with old saved state)
    autoDetectEngine();
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new JsplitAudioProcessor();
}
