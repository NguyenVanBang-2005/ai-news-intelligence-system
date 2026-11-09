// AI processing: POST /api/v1/ai/process (body {}), then poll GET /api/v1/ai/process/{id}
// every few seconds until the job has succeeded or failed.

import { el } from "../js/dom.js";
import { adminErrorText, adminRequest, messageBanner } from "./admin-api.js";

export const POLL_INTERVAL_MS = 3000;
const PROCESS_PATH = "/api/v1/ai/process";
const FINISHED = new Set(["succeeded", "failed"]);

/** The AI processing card. */
export function aiProcessPanel() {
  const view = {
    status: el("div", { className: "job-status", "aria-live": "polite" }),
  };
  view.button = el("button", {
    className: "btn btn-primary", type: "button", text: "Start AI processing", onclick: () => startJob(view),
  });
  view.node = el("section", { className: "card admin-card", "aria-labelledby": "ai-title" }, [
    el("h2", { className: "panel-title", id: "ai-title", text: "AI processing" }),
    el("p", { className: "panel-subtitle", text: "Embeds new articles, groups them into topics and writes summaries. Runs in the background." }),
    view.button,
    view.status,
  ]);
  return view.node;
}

async function startJob(view) {
  if (view.button.disabled) return; // a job is being started or followed
  view.button.disabled = true;
  try {
    const job = await adminRequest(PROCESS_PATH, { method: "POST", body: {} });
    await followJob(view, job);
  } catch (error) {
    view.status.replaceChildren(messageBanner(`AI processing could not run. ${adminErrorText(error)}`, "error"));
  } finally {
    view.button.disabled = false;
  }
}

// Polls until the job has finished, or until the card has left the page (log-out, session end).
async function followJob(view, firstAnswer) {
  let job = firstAnswer;
  showJob(view, job);
  while (!FINISHED.has(job.status)) {
    await wait(POLL_INTERVAL_MS);
    if (!view.node.isConnected) return;
    job = await adminRequest(`${PROCESS_PATH}/${encodeURIComponent(job.id)}`);
    showJob(view, job);
  }
}

function showJob(view, job) {
  const lines = [el("p", { className: "job-line", text: `Job ${job.id}: ${job.status}` })];
  if (job.status === "succeeded") {
    lines.push(el("pre", { className: "job-result", text: JSON.stringify(job.result, null, 2) }));
  } else if (job.status === "failed") {
    lines.push(messageBanner(`The job failed: ${job.error ?? "no error message"}`, "error"));
  } else {
    lines.push(el("p", { className: "state state-loading", text: `Checking again every ${POLL_INTERVAL_MS / 1000} seconds…` }));
  }
  view.status.replaceChildren(...lines);
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
