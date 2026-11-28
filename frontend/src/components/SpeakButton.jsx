import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// Reads text aloud. AI voice (Kokoro on the Kaggle gateway, via /api/speech) when it's on; otherwise, or if it
// fails, the browser's built-in voice. Only one thing plays at a time.
//
//   <SpeakButton text="One answer" />
//   <SpeakButton parts={["Title.", "Section 1 ...", "Section 2 ..."]} label="Listen to notes" />
//
// `parts` are read one after another (the next part's audio is prepared while the current one plays), so long
// notes never hit the voice server's length limit and start playing quickly.

export const SPEEDS = [0.5, 1, 1.5, 2];

// ---- playback speed: one setting for the whole app, remembered in this browser ----
const speed = {
  value: (() => {
    try {
      const v = parseFloat(localStorage.getItem("lw-speech-speed"));
      return SPEEDS.includes(v) ? v : 1;
    } catch {
      return 1;
    }
  })(),
  listeners: new Set(),
  set(v) {
    this.value = v;
    try {
      localStorage.setItem("lw-speech-speed", String(v));
    } catch {
      /* storage blocked: keep it for this session only */
    }
    this.listeners.forEach((fn) => fn(v));
  },
};

function useSpeed() {
  const [v, setV] = useState(speed.value);
  useEffect(() => {
    speed.listeners.add(setV);
    return () => speed.listeners.delete(setV);
  }, []);
  return [v, (x) => speed.set(x)];
}

// ---- shared state ----
const audioCache = new Map(); // text -> object URL (AI voice), so replaying is instant
let aiVoiceOff = false; // after a 501: don't ask the backend again this session
let current = null; // the player that is running: { owner, stop, setRate }

const forSpeech = (text) =>
  String(text).replace(/\s*\[S\d+\]/g, "").replace(/[*_`#]/g, "").replace(/→/g, " to ").replace(/\s+/g, " ").trim();

async function aiAudioUrl(text) {
  let url = audioCache.get(text);
  if (!url) {
    url = URL.createObjectURL(await api.speech(text));
    audioCache.set(text, url);
  }
  return url;
}

function englishVoice() {
  const voices = window.speechSynthesis.getVoices();
  return voices.find((v) => /^en(-|_)/i.test(v.lang) && /natural|neural|google|online/i.test(v.name)) || voices.find((v) => /^en/i.test(v.lang)) || null;
}

// Plays parts in order with the AI voice, falling back to the browser's voice for the rest if the AI voice fails.
function startPlayer(parts, { onVoice, onDone, onError }) {
  const texts = parts.map(forSpeech).filter(Boolean);
  let i = 0;
  let stopped = false;
  let audio = null;
  let mode = aiVoiceOff ? "browser" : "ai";

  const finish = () => {
    if (!stopped) {
      stopped = true;
      onDone();
    }
  };

  const speakBrowser = () => {
    const synth = window.speechSynthesis;
    if (!synth) return onError(new Error("This browser can't read text aloud."));
    synth.cancel();
    const u = new SpeechSynthesisUtterance(texts[i]);
    u.voice = englishVoice();
    u.lang = u.voice?.lang || "en-US";
    u.rate = speed.value;
    u.onend = () => {
      if (stopped || u._replaced) return;
      i += 1;
      i < texts.length ? speakBrowser() : finish();
    };
    u.onerror = (e) => {
      if (!stopped && !u._replaced && e.error !== "interrupted" && e.error !== "canceled") onError(new Error("The browser voice failed."));
    };
    player.utterance = u;
    onVoice("Browser voice");
    synth.speak(u);
  };

  const playAi = async () => {
    try {
      const url = await aiAudioUrl(texts[i]);
      if (stopped) return;
      if (i + 1 < texts.length) aiAudioUrl(texts[i + 1]).catch(() => {}); // prepare the next part meanwhile
      audio = new Audio(url);
      audio.preservesPitch = true; // faster or slower without sounding like a chipmunk
      audio.playbackRate = speed.value;
      audio.onended = () => {
        if (stopped) return;
        i += 1;
        i < texts.length ? playAi() : finish();
      };
      await audio.play();
      onVoice("AI voice");
    } catch (e) {
      if (stopped) return;
      if (e.status === 501) aiVoiceOff = true;
      mode = "browser"; // AI voice off or failed: read this part and the rest with the browser
      speakBrowser();
    }
  };

  const player = {
    utterance: null,
    stop() {
      stopped = true;
      if (audio) {
        audio.pause();
        audio.currentTime = 0;
      }
      if (mode === "browser") window.speechSynthesis?.cancel();
    },
    setRate(r) {
      if (mode === "ai" && audio) audio.playbackRate = r; // instant, mid-sentence
      if (mode === "browser" && player.utterance && !stopped) {
        player.utterance._replaced = true; // the browser can't change speed mid-utterance: restart this part
        speakBrowser();
      }
    },
  };

  if (!texts.length) {
    setTimeout(finish, 0);
  } else if (mode === "ai") {
    playAi();
  } else {
    speakBrowser();
  }
  return player;
}

export default function SpeakButton({ text, parts, label = "Listen", compact = false }) {
  const [state, setState] = useState("idle"); // idle | loading | playing
  const [voice, setVoice] = useState(null);
  const [error, setError] = useState(null);
  const [rate, setRate] = useSpeed();
  const me = useRef({});

  useEffect(() => () => { if (current?.owner === me.current) stop(); }, []); // stop when the page or bubble goes away

  useEffect(() => {
    if (current?.owner === me.current) current.setRate(rate);
  }, [rate]);

  function stop() {
    if (current?.owner === me.current) {
      current.stop();
      current = null;
    }
    setState("idle");
  }

  const toggle = () => {
    setError(null);
    if (state !== "idle") return stop();
    if (current) {
      current.stop(); // something else was playing
      current.owner.reset?.();
    }
    setState("loading");
    me.current.reset = () => setState("idle");
    const player = startPlayer(parts || [text], {
      onVoice: (v) => {
        setVoice(v);
        setState("playing");
      },
      onDone: () => {
        if (current?.owner === me.current) current = null;
        setState("idle");
      },
      onError: (e) => {
        if (current?.owner === me.current) current = null;
        setState("idle");
        setError(e.message);
      },
    });
    current = { owner: me.current, stop: player.stop, setRate: player.setRate };
  };

  const icon = state === "playing" ? "■" : state === "loading" ? "…" : "🔊";
  const text_ = state === "loading" ? (compact ? "" : "Preparing voice…") : state === "playing" ? (compact ? "" : "Stop") : label;
  return (
    <span className={`speak ${compact ? "compact" : ""}`}>
      <button type="button" className={`speak-btn ${state}`} onClick={toggle} aria-label={state === "idle" ? label || "Read this section aloud" : "Stop reading"}>
        {icon} {text_}
      </button>
      {!compact && (
        <label className="speed" title="Playback speed (one setting for every Listen button)">
          <select value={rate} onChange={(e) => setRate(parseFloat(e.target.value))} aria-label="Playback speed">
            {SPEEDS.map((s) => (
              <option key={s} value={s}>{s}×</option>
            ))}
          </select>
        </label>
      )}
      {voice && state === "playing" && <span className="muted small-inline">{voice}</span>}
      {error && <span className="muted small-inline">{error}</span>}
    </span>
  );
}
