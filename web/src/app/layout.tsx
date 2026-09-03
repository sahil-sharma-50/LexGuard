import type { Metadata } from "next"
import { Archivo, Azeret_Mono } from "next/font/google"
import "./globals.css"

/**
 * Court Record type system: Archivo carries every authored word (tight, heavy,
 * newsprint-grotesque); Azeret Mono is the clerk that sets the machine record:
 * kickers, indices, statuses, IDs, timestamps, control labels.
 */
const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
})

const azeretMono = Azeret_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
})

export const metadata: Metadata = {
  title: "Lexguard: AI argues. Risk decides.",
  description:
    "Autonomous options court on Alpaca paper: an LLM may only argue or refuse; deterministic risk code certifies and executes. Live command center, hashed ledger, stop-only human controls.",
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${archivo.variable} ${azeretMono.variable}`}>{children}</body>
    </html>
  )
}
