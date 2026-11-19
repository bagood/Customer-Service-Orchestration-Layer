// Contract-shaped fixtures for Chat Completions, not a real intent classifier.
const http = require("http");
const requests = [];
const headers = { "Content-Type": "application/json" };
function send(res, status, body) {
  res.writeHead(status, headers);
  res.end(JSON.stringify(body));
}
http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/__requests") {
    return send(res, 200, requests);
  }
  if (req.method === "DELETE" && req.url === "/__requests") {
    requests.length = 0;
    return send(res, 200, { reset: true });
  }
  if (req.method !== "POST" || req.url !== "/v1/chat/completions") {
    return send(res, 501, { error: "This simulation only models Chat Completions" });
  }
  let raw = "";
  // The CLI interceptor may already have parsed the body.
  if (req.body === undefined) {
    for await (const chunk of req) raw += chunk;
  }
  let body;
  try { body = req.body === undefined ? JSON.parse(raw) : req.body; }
  catch { return send(res, 400, { error: "Invalid JSON" }); }
  if (!body.model || !Array.isArray(body.messages) || body.stream !== false ||
      body.messages[0]?.role !== "system" || body.messages[1]?.role !== "user" ||
      !["json_object", "json_schema"].includes(body.response_format?.type)) {
    return send(res, 400, { error: "Unexpected caller contract" });
  }
  requests.push({ model: body.model, messages: body.messages,
                  response_format: body.response_format,
                  hasAuthorization: req.headers.authorization === "Bearer test-secret" });
  if (body.model === "sim-500") return send(res, 500, { error: "upstream test-secret" });
  if (body.model === "sim-429") return send(res, 429, { error: "rate limited" });
  if (body.model === "sim-timeout") {
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  if (body.model === "sim-envelope") return send(res, 200, { choices: [{ message: "invalid" }] });
  let input;
  try { input = JSON.parse(body.messages[1].content); }
  catch { return send(res, 400, { error: "Expected JSON-encoded user data" }); }
  const fixtures = {
    "I want to buy data": "buy_package",
    "Saya mau transfer pulsa": "send_credit",
    "Buy a package": "buy_package",
  };
  let intent = fixtures[input.message] ?? null;
  let reason = intent ? "recognized" : "unsupported";
  if (input.message === "Both please") reason = "ambiguous";
  if (input.message === "The first option" && input.prior_message === "Both please") {
    intent = "buy_package"; reason = "recognized";
  }
  let content = JSON.stringify({ intent, reason });
  if (body.model === "sim-invalid") content = JSON.stringify({ intent: "refund", reason: "recognized" });
  if (body.model === "sim-extra") content = JSON.stringify({ intent: "buy_package", reason: "recognized", authorized: true });
  if (body.model === "sim-inconsistent") content = JSON.stringify({ intent: null, reason: "recognized" });
  if (body.model === "sim-malformed") content = "not JSON";
  const message = { role: "assistant", content };
  if (body.model === "sim-refusal") message.refusal = "Cannot classify";
  return send(res, 200, {
    id: "chatcmpl-simulation", object: "chat.completion", created: 0, model: body.model,
    choices: [{ index: 0, message, finish_reason: body.model === "sim-truncated" ? "length" : "stop" }],
  });
}).listen(Number(process.env.PORT || 4500), "127.0.0.1");
