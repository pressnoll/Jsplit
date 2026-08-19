#include "PluginEditor.h"

namespace
{
    const juce::Identifier kInputFile  { "inputFile" };
    const juce::Identifier kOutputDir  { "outputDir" };
    const juce::Identifier kQuality    { "quality" };
    const juce::Identifier kStems      { "stems" };
    const juce::Identifier kPythonPath { "pythonPath" };
    const juce::Identifier kEngineHome { "engineHome" };

    juce::StringArray stemsForTier (const juce::String& tier)
    {
        if (tier == "fast" || tier == "balanced")
            return { "vocals", "drums", "bass", "other" };
        return { "vocals", "drums", "bass", "other", "guitar", "piano" }; // full / max
    }

    juce::String tierBlurb (const juce::String& tier)
    {
        if (tier == "fast")     return "htdemucs · 4 stems · quickest";
        if (tier == "balanced") return "htdemucs_ft · 4 stems · fine-tuned, cleaner";
        if (tier == "full")     return "htdemucs_6s · 6 stems · + guitar & piano";
        if (tier == "max")      return "6s + RoFormer · 6 stems · cleanest vocal (slowest)";
        return {};
    }

    const juce::Colour kBg     { 0xff1e1f26 };
    const juce::Colour kPanel  { 0xff282a36 };
    const juce::Colour kAccent { 0xff8be9fd };
    const juce::Colour kText   { 0xffe6e6e6 };
    const juce::Colour kMuted  { 0xff9aa0b0 };
}

JsplitAudioProcessorEditor::JsplitAudioProcessorEditor (JsplitAudioProcessor& p)
    : juce::AudioProcessorEditor (&p), proc (p)
{
    auto& s = proc.state();

    // ── header ──
    title.setText ("Jsplit", juce::dontSendNotification);
    title.setFont (juce::Font (22.0f, juce::Font::bold));
    title.setColour (juce::Label::textColourId, kAccent);
    addAndMakeVisible (title);

    subtitle.setText ("Clarity-first offline stem separation", juce::dontSendNotification);
    subtitle.setColour (juce::Label::textColourId, kMuted);
    addAndMakeVisible (subtitle);

    // ── 1 · song ──
    addAndMakeVisible (loadButton);
    loadButton.onClick = [this]
    {
        chooser = std::make_unique<juce::FileChooser> ("Choose a song",
                                                       juce::File(),
                                                       "*.wav;*.mp3;*.flac;*.m4a;*.ogg;*.aiff;*.aif");
        chooser->launchAsync (juce::FileBrowserComponent::openMode
                            | juce::FileBrowserComponent::canSelectFiles,
            [this] (const juce::FileChooser& fc)
            {
                auto f = fc.getResult();
                if (f.existsAsFile())
                {
                    proc.state().setProperty (kInputFile, f.getFullPathName(), nullptr);
                    fileLabel.setText (f.getFileName(), juce::dontSendNotification);
                }
            });
    };

    fileLabel.setColour (juce::Label::textColourId, kText);
    fileLabel.setText (s.getProperty (kInputFile, "").toString().isEmpty()
                           ? "No song loaded"
                           : juce::File (s[kInputFile].toString()).getFileName(),
                       juce::dontSendNotification);
    addAndMakeVisible (fileLabel);

    // ── 2 · quality ──
    qualityBox.addItemList ({ "fast", "balanced", "full", "max" }, 1);
    qualityBox.setText (s.getProperty (kQuality, "full").toString(), juce::dontSendNotification);
    qualityBox.onChange = [this]
    {
        proc.state().setProperty (kQuality, qualityBox.getText(), nullptr);
        qualityHint.setText (tierBlurb (qualityBox.getText()), juce::dontSendNotification);
        rebuildStemToggles();
    };
    addAndMakeVisible (qualityBox);

    qualityHint.setColour (juce::Label::textColourId, kMuted);
    qualityHint.setText (tierBlurb (qualityBox.getText()), juce::dontSendNotification);
    addAndMakeVisible (qualityHint);

    // ── 3 · stems ──
    stemsHeader.setText ("Stems to export", juce::dontSendNotification);
    stemsHeader.setColour (juce::Label::textColourId, kMuted);
    addAndMakeVisible (stemsHeader);
    rebuildStemToggles();

    // ── 4 · export ──
    outDirLabel.setColour (juce::Label::textColourId, kText);
    outDirLabel.setText (s.getProperty (kOutputDir, "").toString(), juce::dontSendNotification);
    addAndMakeVisible (outDirLabel);

    addAndMakeVisible (changeOutButton);
    changeOutButton.onClick = [this]
    {
        chooser = std::make_unique<juce::FileChooser> ("Choose export folder",
                                                       juce::File (proc.state()[kOutputDir].toString()));
        chooser->launchAsync (juce::FileBrowserComponent::openMode
                            | juce::FileBrowserComponent::canSelectDirectories,
            [this] (const juce::FileChooser& fc)
            {
                auto d = fc.getResult();
                if (d != juce::File())
                {
                    proc.state().setProperty (kOutputDir, d.getFullPathName(), nullptr);
                    outDirLabel.setText (d.getFullPathName(), juce::dontSendNotification);
                }
            });
    };

    // ── action ──
    generateButton.setColour (juce::TextButton::buttonColourId, kAccent);
    generateButton.setColour (juce::TextButton::textColourOffId, juce::Colour (0xff0b0c10));
    generateButton.onClick = [this] { onGenerate(); };
    addAndMakeVisible (generateButton);

    openFolderButton.setEnabled (false);
    openFolderButton.onClick = [this]
    {
        if (lastOutputFolder.isDirectory())
            lastOutputFolder.revealToUser();
    };
    addAndMakeVisible (openFolderButton);

    progressBar.setColour (juce::ProgressBar::foregroundColourId, kAccent);
    progressBar.setColour (juce::ProgressBar::backgroundColourId, kPanel);
    addChildComponent (progressBar); // hidden until busy

    // ── status log ──
    statusLog.setMultiLine (true);
    statusLog.setReadOnly (true);
    statusLog.setCaretVisible (false);
    statusLog.setScrollbarsShown (true);
    statusLog.setColour (juce::TextEditor::backgroundColourId, kPanel);
    statusLog.setColour (juce::TextEditor::textColourId, kText);
    statusLog.setFont (juce::Font (juce::Font::getDefaultMonospacedFontName(), 12.0f, 0));
    statusLog.setText ("Ready.\n", juce::dontSendNotification);
    addAndMakeVisible (statusLog);

    // ── settings strip (engine location) ──
    auto mkPathLabel = [this] (juce::Label& l, const juce::String& text)
    {
        l.setColour (juce::Label::textColourId, kMuted);
        l.setFont (juce::Font (11.0f));
        l.setText (text, juce::dontSendNotification);
        addAndMakeVisible (l);
    };
    mkPathLabel (pyLabel,   "python: "  + s.getProperty (kPythonPath, "(not set)").toString());
    mkPathLabel (homeLabel, "engine: "  + s.getProperty (kEngineHome, "(not set)").toString());

    addAndMakeVisible (pyBrowse);
    pyBrowse.onClick = [this]
    {
        chooser = std::make_unique<juce::FileChooser> ("Locate Python interpreter", juce::File());
        chooser->launchAsync (juce::FileBrowserComponent::openMode
                            | juce::FileBrowserComponent::canSelectFiles,
            [this] (const juce::FileChooser& fc)
            {
                auto f = fc.getResult();
                if (f.existsAsFile())
                {
                    proc.state().setProperty (kPythonPath, f.getFullPathName(), nullptr);
                    pyLabel.setText ("python: " + f.getFullPathName(), juce::dontSendNotification);
                }
            });
    };

    addAndMakeVisible (homeBrowse);
    homeBrowse.onClick = [this]
    {
        chooser = std::make_unique<juce::FileChooser> ("Locate engine folder (has scripts/split.py)",
                                                       juce::File());
        chooser->launchAsync (juce::FileBrowserComponent::openMode
                            | juce::FileBrowserComponent::canSelectDirectories,
            [this] (const juce::FileChooser& fc)
            {
                auto d = fc.getResult();
                if (d != juce::File())
                {
                    proc.state().setProperty (kEngineHome, d.getFullPathName(), nullptr);
                    homeLabel.setText ("engine: " + d.getFullPathName(), juce::dontSendNotification);
                }
            });
    };

    setSize (560, 720);
    setResizable (true, true);
    setResizeLimits (520, 640, 900, 1100);
}

JsplitAudioProcessorEditor::~JsplitAudioProcessorEditor()
{
    bridge.cancel();
}

void JsplitAudioProcessorEditor::rebuildStemToggles()
{
    // remember current checks
    juce::StringArray checked;
    for (auto* t : stemToggles)
        if (t->getToggleState())
            checked.add (t->getButtonText().toLowerCase());

    // first build? seed from saved state
    if (stemToggles.isEmpty())
        checked.addTokens (proc.state().getProperty (kStems, "").toString(), ",", "");

    stemToggles.clear();
    for (auto& stem : stemsForTier (qualityBox.getText()))
    {
        auto* t = new juce::ToggleButton (stem.substring (0, 1).toUpperCase() + stem.substring (1));
        t->setColour (juce::ToggleButton::textColourId, kText);
        t->setToggleState (checked.isEmpty() || checked.contains (stem), juce::dontSendNotification);
        t->onClick = [this] { pushSelectionToState(); };
        addAndMakeVisible (t);
        stemToggles.add (t);
    }
    pushSelectionToState();
    resized();
}

void JsplitAudioProcessorEditor::pushSelectionToState()
{
    juce::StringArray sel;
    for (auto* t : stemToggles)
        if (t->getToggleState())
            sel.add (t->getButtonText().toLowerCase());
    proc.state().setProperty (kStems, sel.joinIntoString (","), nullptr);
}

void JsplitAudioProcessorEditor::onGenerate()
{
    if (bridge.isRunning())
        return;

    SeparationBridge::Config cfg;
    auto& s = proc.state();
    cfg.pythonPath = s.getProperty (kPythonPath, "").toString();
    cfg.engineHome = juce::File (s.getProperty (kEngineHome, "").toString());
    cfg.inputFile  = juce::File (s.getProperty (kInputFile, "").toString());
    cfg.outputDir  = juce::File (s.getProperty (kOutputDir, "").toString());
    cfg.quality    = s.getProperty (kQuality, "full").toString();
    cfg.stemsCsv   = s.getProperty (kStems, "").toString();

    if (auto err = bridge.validate (cfg); err.isNotEmpty())
    {
        appendStatus ("• " + err);
        return;
    }

    statusLog.clear();
    appendStatus ("Starting — quality=" + cfg.quality + ", stems=" + cfg.stemsCsv);
    appendStatus ("(First run downloads model weights — this can take a while.)");
    setBusy (true);

    juce::Component::SafePointer<JsplitAudioProcessorEditor> safe (this);
    bridge.onLine = [safe] (const juce::String& line)
    {
        juce::MessageManager::callAsync ([safe, line] { if (safe) safe->appendStatus (line); });
    };
    bridge.onFinished = [safe] (bool ok, const juce::File& out)
    {
        juce::MessageManager::callAsync ([safe, ok, out]
        {
            if (! safe) return;
            safe->setBusy (false);
            if (ok)
            {
                safe->lastOutputFolder = out;
                safe->openFolderButton.setEnabled (out.isDirectory());
                safe->appendStatus ("Done — stems exported to:");
                safe->appendStatus (out.getFullPathName());
            }
            else
            {
                safe->appendStatus ("Separation failed — see the log above.");
            }
        });
    };

    bridge.start (cfg);
}

void JsplitAudioProcessorEditor::appendStatus (const juce::String& line)
{
    statusLog.moveCaretToEnd();
    statusLog.insertTextAtCaret (line + "\n");
    statusLog.moveCaretToEnd();
}

void JsplitAudioProcessorEditor::setBusy (bool busy)
{
    generateButton.setEnabled (! busy);
    generateButton.setButtonText (busy ? "Working…" : "Generate stems");
    progressBar.setVisible (busy);
    if (busy) { progress = 0.0; startTimerHz (30); }
    else      { stopTimer(); progress = 0.0; }
}

void JsplitAudioProcessorEditor::timerCallback()
{
    // simple looping "busy" animation (we can't know true % across model load + inference)
    progress += 0.012;
    if (progress >= 1.0) progress = 0.0;
    progressBar.repaint();
}

void JsplitAudioProcessorEditor::paint (juce::Graphics& g)
{
    g.fillAll (kBg);
}

void JsplitAudioProcessorEditor::resized()
{
    auto r = getLocalBounds().reduced (16);

    title.setBounds    (r.removeFromTop (30));
    subtitle.setBounds (r.removeFromTop (18));
    r.removeFromTop (10);

    auto row = [&r] (int h, int gap = 8) { auto a = r.removeFromTop (h); r.removeFromTop (gap); return a; };

    // 1 · song
    {
        auto line = row (30);
        loadButton.setBounds (line.removeFromLeft (120));
        line.removeFromLeft (10);
        fileLabel.setBounds (line);
    }
    // 2 · quality
    {
        auto line = row (28);
        qualityBox.setBounds (line.removeFromLeft (120));
        line.removeFromLeft (12);
        qualityHint.setBounds (line);
    }
    // 3 · stems
    stemsHeader.setBounds (row (18, 4));
    {
        // lay toggles in a 3-column grid
        int cols = 3, cw = r.getWidth() / cols, rh = 26;
        int rows = (stemToggles.size() + cols - 1) / cols;
        auto grid = r.removeFromTop (rows * rh);
        for (int i = 0; i < stemToggles.size(); ++i)
        {
            int cx = grid.getX() + (i % cols) * cw;
            int cy = grid.getY() + (i / cols) * rh;
            stemToggles[i]->setBounds (cx, cy, cw - 6, rh - 4);
        }
        r.removeFromTop (10);
    }
    // 4 · export
    {
        auto line = row (26);
        changeOutButton.setBounds (line.removeFromRight (90));
        line.removeFromRight (8);
        outDirLabel.setBounds (line);
    }
    r.removeFromTop (4);

    // action
    generateButton.setBounds (row (40));
    progressBar.setBounds    (row (12));
    openFolderButton.setBounds (row (26).removeFromLeft (170));
    r.removeFromTop (4);

    // status log — take most of the remaining space, leave room for settings
    auto settingsH = 60;
    statusLog.setBounds (r.removeFromTop (juce::jmax (80, r.getHeight() - settingsH)));
    r.removeFromTop (6);

    // settings strip
    {
        auto line = r.removeFromTop (22);
        pyBrowse.setBounds (line.removeFromLeft (80));
        line.removeFromLeft (8);
        pyLabel.setBounds (line);
    }
    r.removeFromTop (4);
    {
        auto line = r.removeFromTop (22);
        homeBrowse.setBounds (line.removeFromLeft (80));
        line.removeFromLeft (8);
        homeLabel.setBounds (line);
    }
}
