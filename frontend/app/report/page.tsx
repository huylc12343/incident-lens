import { Header } from "../../components/Header";
import { ReportContent } from "../../components/ReportContent";

export default function ReportPage() {
  return (
    <>
      <Header />
      <main className="report-page-shell"><ReportContent /></main>
    </>
  );
}
