"use client";

import { useEffect, useState } from "react";
import ReportView from "@/components/ReportView";
import { fetchJson } from "@/lib/data";
import { LangProvider, LangSwitch, useLang } from "@/lib/i18n";

// Print-friendly, standalone report page. Opened in a new tab by the panel's
// "Download PDF" button; the user prints / saves as PDF from here.
export default function ReportPrintPage({ params }: { params: { company: string } }) {
  return (
    <LangProvider>
      <ReportPrint company={decodeURIComponent(params.company)} />
    </LangProvider>
  );
}

function ReportPrint({ company }: { company: string }) {
  const { t, name, lang } = useLang();
  const [report, setReport] = useState<any>(undefined);

  useEffect(() => {
    fetchJson<Record<string, any>>("/data/reports.bundle.json")
      .then((rb) => setReport(rb[company] ?? null))
      .catch(() => setReport(null));
  }, [company]);

  useEffect(() => {
    document.title = `${name(company)} — ${t("Equity Research")}`;
  }, [company, lang, name, t]);

  return (
    <div className="print-scope">
      <div className="print-bar">
        <button className="btn" onClick={() => window.print()}>
          {t("Print / Save as PDF")}
        </button>
        <LangSwitch />
      </div>
      {report === undefined && <p>{t("Loading…")}</p>}
      {report === null && <p>{t("No report found for {name}.", { name: name(company) })}</p>}
      {report && (
        <div className="print-body">
          <ReportView report={report} />
        </div>
      )}
    </div>
  );
}
