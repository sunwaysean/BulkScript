// src/auth/Login.js
import React, { useState } from "react";
import { signInWithEmailAndPassword } from "firebase/auth";
import { auth, loginWithGoogle } from "../firebase";
import { useNavigate, Link } from "react-router-dom";
import "./Auth.css";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const nav = useNavigate();
  const onSubmit = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      await signInWithEmailAndPassword(auth, email, password);
      nav("/");
    } catch (e) {
      setErr(e.message);
    }
  };

  const onGoogle = async () => {
    try {
      await loginWithGoogle();
      nav("/");
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>BulkScript — Login</h2>
        <form onSubmit={onSubmit}>
          <label>Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} required />
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <button type="submit">Login</button>
        </form>

        <button className="ghost" onClick={onGoogle}>Sign in with Google</button>

        <p>
          Don't have an account? <Link to="/register">Register</Link>
        </p>
        {err && <p className="error">{err}</p>}
      </div>
    </div>
  );
}
