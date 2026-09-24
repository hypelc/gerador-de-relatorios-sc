import { DM_Mono, Manrope, Source_Sans_3 } from "next/font/google";

import "../styles.css";

const sourceSans = Source_Sans_3({
  subsets: ["latin"],
  variable: "--font-source-sans",
  display: "swap",
});

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-manrope",
  display: "swap",
});

const dmMono = DM_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-dm-mono",
  display: "swap",
});

export const metadata = {
  title: "Gerador de Relatórios SC",
  description:
    "Importe indicadores de Santa Catarina, confira os dados e gere relatórios visuais.",
};

export const viewport = {
  themeColor: "#103a42",
};

export default function RootLayout({ children }) {
  return (
    <html
      lang="pt-BR"
      className={`${sourceSans.variable} ${manrope.variable} ${dmMono.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
