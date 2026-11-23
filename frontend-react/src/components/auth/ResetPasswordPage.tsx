import React from "react";
import { useSearchParams } from "react-router-dom";
import { ForgotPasswordPage } from "./ForgotPasswordPage";

export const ResetPasswordPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || searchParams.get("reset_token") || "";

  return <ForgotPasswordPage initialStep={token ? "password" : "request"} />;
};

export default ResetPasswordPage;
