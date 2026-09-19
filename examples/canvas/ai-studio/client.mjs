const form = document.querySelector("form");
const prompt = document.querySelector("textarea");
const output = document.querySelector("output");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  output.textContent = "Running bounded local preview…";
  try {
    const response = await fetch("/api/preview", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt: prompt.value }), signal: AbortSignal.timeout(20_000),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    output.textContent = body.output;
  } catch (error) { output.textContent = `Preview failed: ${error.message}`; }
});
