"use client";
import { DeliveriesBoard } from "@/components/admin/DeliveriesBoard";
import { PageTop } from "@/components/admin/ui";
import { useStaff } from "@/components/admin/AdminShell";

export default function DeliveriesPage() {
  const user = useStaff();
  return (
    <>
      <PageTop title={user.role === "courier" ? "Мои доставки" : "Доставки по интервалам"} />
      <DeliveriesBoard />
    </>
  );
}
