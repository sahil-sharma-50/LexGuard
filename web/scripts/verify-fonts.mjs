import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
import { dirname, isAbsolute, join, relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const fontsDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "../src/fonts")
const manifestPath = join(fontsDirectory, "manifest.sha256")
const manifest = readFileSync(manifestPath, "utf8")
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter(Boolean)

const errors = []

for (const line of manifest) {
  const match = line.match(/^([a-f0-9]{64})\s+(.+)$/i)
  if (!match) {
    errors.push("Invalid manifest entry: " + line)
    continue
  }

  const [, expectedHash, filename] = match
  const fontPath = resolve(fontsDirectory, filename)
  const relativePath = relative(fontsDirectory, fontPath)

  if (isAbsolute(relativePath) || relativePath.startsWith("..")) {
    errors.push("Manifest entry escapes the font directory: " + filename)
    continue
  }

  try {
    const actualHash = createHash("sha256").update(readFileSync(fontPath)).digest("hex")
    if (actualHash !== expectedHash.toLowerCase()) {
      errors.push(filename + ": expected " + expectedHash + ", got " + actualHash)
    }
  } catch {
    errors.push(filename + ": file is missing or unreadable")
  }
}

if (errors.length > 0) {
  console.error("Font manifest verification failed:")
  for (const error of errors) console.error("- " + error)
  process.exitCode = 1
} else {
  console.log("Font manifest verified: " + manifest.length + " files")
}
