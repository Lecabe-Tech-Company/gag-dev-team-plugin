import { spawn } from "node:child_process";
import path from "node:path";
import { isRecord, type SnapshotFilters } from "./security";

const maximumOutputBytes = 8 * 1024 * 1024;
const processTimeoutMs = 30_000;

export async function readSnapshot(
  binding: Record<string, unknown>,
  filters: SnapshotFilters,
): Promise<Record<string, unknown>> {
  const pluginRoot = process.env.GAG_DASHBOARD_PLUGIN_ROOT;
  const pythonExecutable = process.env.GAG_DASHBOARD_PYTHON;

  if (!pluginRoot || !path.isAbsolute(pluginRoot) || !pythonExecutable || !path.isAbsolute(pythonExecutable)) {
    throw new Error("Dashboard backend is unavailable.");
  }

  const scriptPath = path.join(pluginRoot, "scripts", "gag_dev_team.py");
  const args = ["-X", "utf8", scriptPath, "environment", "snapshot", "--bound"];

  for (const [name, value] of Object.entries(filters)) {
    const flagName = name === "goal_id" ? "goal-id" : name === "agent_id" ? "agent-id" : name;
    args.push(`--${flagName}`, value);
  }

  const output = await runPython(pythonExecutable, args, pluginRoot, JSON.stringify(binding));
  let snapshot: unknown;
  try {
    snapshot = JSON.parse(output);
  } catch {
    throw new Error("Dashboard backend returned an invalid snapshot.");
  }

  if (!isRecord(snapshot) || snapshot.schema_version !== 1) {
    throw new Error("Dashboard backend returned an unsupported snapshot.");
  }

  return snapshot;
}

function runPython(
  executable: string,
  args: string[],
  workingDirectory: string,
  input: string,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, {
      cwd: workingDirectory,
      env: { ...process.env, PYTHONUTF8: "1" },
      shell: false,
      stdio: ["pipe", "pipe", "pipe"],
    });
    const outputChunks: Buffer[] = [];
    let outputBytes = 0;
    let settled = false;
    const timeout = setTimeout(() => {
      child.kill();
      finish(new Error("Dashboard backend timed out."));
    }, processTimeoutMs);

    const finish = (error?: Error, output?: string) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      if (error) reject(error);
      else resolve(output ?? "");
    };

    child.stdout.on("data", (chunk: Buffer) => {
      outputBytes += chunk.length;
      if (outputBytes > maximumOutputBytes) {
        child.kill();
        finish(new Error("Dashboard backend output exceeded the allowed size."));
        return;
      }
      outputChunks.push(chunk);
    });

    child.stderr.on("data", () => {
      // Keep backend diagnostics out of the browser response and process logs.
    });

    child.once("error", () => finish(new Error("Dashboard backend could not start.")));
    child.once("close", (code) => {
      if (code !== 0) {
        finish(new Error("Dashboard backend failed."));
        return;
      }
      finish(undefined, Buffer.concat(outputChunks).toString("utf8"));
    });

    child.stdin.once("error", () => finish(new Error("Dashboard backend input failed.")));
    child.stdin.end(input, "utf8");
  });
}
