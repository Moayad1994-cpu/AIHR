// Language toggle
const setLang = (lng) => {
  document.documentElement.lang = lng === 'ar' ? 'ar' : 'en';
  document.documentElement.dir = lng === 'ar' ? 'rtl' : 'ltr';
  const dict = window.I18N[lng];
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    if (dict[key]) el.textContent = dict[key];
  });
};
document.addEventListener("DOMContentLoaded", () => {
  const ar = document.getElementById("lang-ar");
  const en = document.getElementById("lang-en");
  if (ar) ar.addEventListener("click", () => setLang('ar'));
  if (en) en.addEventListener("click", () => setLang('en'));
  setLang('en'); // default

  // Chatbot toggle
  const chatToggle = document.getElementById("chat-toggle");
  const chatClose = document.getElementById("chat-close");
  const chatbot = document.getElementById("chatbot");
  const chatBody = document.getElementById("chat-body");
  const chatText = document.getElementById("chat-text");
  const chatSend = document.getElementById("chat-send");
  if (chatToggle) chatToggle.addEventListener("click", ()=> chatbot.style.display = "flex");
  if (chatClose) chatClose.addEventListener("click", ()=> chatbot.style.display = "none");

  const addMsg = (cls, text) => {
    const div = document.createElement("div");
    div.className = "msg " + cls;
    div.textContent = text;
    chatBody.appendChild(div);
    chatBody.scrollTop = chatBody.scrollHeight;
  };

  const send = async () => {
    const text = chatText.value.trim();
    if (!text) return;
    addMsg("user", text);
    chatText.value = "";
    try {
      const r = await fetch("/api/chat", {
        method:"POST",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ message: text })
      });
      const data = await r.json();
      if (data.reply) addMsg("bot", data.reply);
      else addMsg("bot", data.error || "Error");
    } catch (e) {
      addMsg("bot", "Network error");
    }
  };
  if (chatSend) chatSend.addEventListener("click", send);
  if (chatText) chatText.addEventListener("keydown", (e)=> { if (e.key === "Enter") send(); });
});
