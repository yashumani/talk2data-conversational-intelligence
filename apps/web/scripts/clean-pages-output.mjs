import { rm } from "node:fs/promises";
import { resolve } from "node:path";

const output = resolve(process.cwd(), "../../site/workspace");
await rm(output, { recursive: true, force: true });
