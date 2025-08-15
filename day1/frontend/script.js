// --- Generate or get session_id from URL ---
function getSessionId() {
  const urlParams = new URLSearchParams(window.location.search);
  let sessionId = urlParams.get("session_id");

  if (!sessionId) {
    sessionId = Math.random().toString(36).substring(2, 10);
    urlParams.set("session_id", sessionId);
    window.history.replaceState({}, "", `${window.location.pathname}?${urlParams}`);
  }
  return sessionId;
}
const sessionId = getSessionId();

// -------------------- Shared message handler --------------------
function appendMessage(content, sender, isHTML = false) {
  const chatBox = document.getElementById("chat-box");
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${sender}`;
  msgDiv.innerHTML = isHTML ? content : content;
  chatBox.appendChild(msgDiv);
  chatBox.scrollTop = chatBox.scrollHeight;
  return msgDiv;
}

// -------------------- TEXT to LLM+TTS --------------------
async function submitText() {
  const input = document.getElementById("textInput");
  const text = input.value.trim();
  if (!text) return;

  appendMessage(text, "user");
  input.value = "";

  const loadingMsg = appendMessage("🤖 Thinking & generating voice...", "bot");

  try {
    const response = await fetch(`/agent/chat/${sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text })
    });

    const data = await response.json();
    loadingMsg.remove();

    if (!data.success) {
      console.error(`Stage ${data.stage} failed: ${data.error}`);
      return;
    }

    appendMessage(data.gemini_text, "bot");

    // Play all returned audio files sequentially
    for (let url of data.audio_urls) {
      const audio = new Audio(url);
      await new Promise(resolve => {
        audio.onended = resolve;
        audio.play();
      });
    }

    startBtn.click(); // Restart mic
  } catch (err) {
    loadingMsg.remove();
    console.error(err);
  }
}

// -------------------- Mic Recording Logic --------------------
let mediaRecorder;
let audioChunks = [];

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");

startBtn.addEventListener("click", async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];

    mediaRecorder.ondataavailable = event => {
      if (event.data.size > 0) {
        audioChunks.push(event.data);
      }
    };

    startBtn.disabled = true;
    stopBtn.disabled = false;
    mediaRecorder.start();
  } catch (err) {
    alert("Microphone access denied or not supported.");
    console.error("Microphone error:", err);
  }
});

stopBtn.addEventListener("click", () => {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();

    mediaRecorder.onstop = async () => {
      await uploadAndLLM();
    };

    startBtn.disabled = false;
    stopBtn.disabled = true;
  }
});

// -------------------- Day 10 Agent Bot --------------------
async function uploadAndLLM() {
  const formData = new FormData();
  const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
  formData.append("file", audioBlob, "query.webm");

  const statusMsg = appendMessage("🤖 Thinking & generating voice...", "bot");

  try {
    const response = await fetch(`/agent/chat/${sessionId}`, {
      method: "POST",
      body: formData
    });

    if (!response.ok) throw new Error("Agent chat failed");

    const data = await response.json();
    statusMsg.remove();

    // Show last user message from history
    const userMsg = data.history[data.history.length - 2]?.content || "";
    appendMessage(userMsg, "user");

    // Show assistant reply
    appendMessage(data.gemini_text, "bot");

    // Play all returned audio files sequentially
    for (let url of data.audio_urls) {
      const audio = new Audio(url);
      await new Promise(resolve => {
        audio.onended = resolve;
        audio.play();
      });
    }

    // Restart recording after bot finishes
    startBtn.click();
  } catch (error) {
    console.error(error);
    statusMsg.remove();
    appendMessage("❌ Agent chat failed.", "bot");
  }
}
