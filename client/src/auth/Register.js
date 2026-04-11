import React, { useState } from "react";
import { createUserWithEmailAndPassword } from "firebase/auth";
import { auth } from "../firebase";
import { useNavigate, Link } from "react-router-dom";
import "./Auth.css";

export default function Register() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const nav = useNavigate();

  const onSubmit = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      await createUserWithEmailAndPassword(auth, email, password);
      nav("/");
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>BulkScript Register</h2>
        <form onSubmit={onSubmit}>
          <label>Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} required />
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <button type="submit">Create account</button>
        </form>

        <p>
          Already have an account? <Link to="/login">Login</Link>
        </p>
        {err && <p className="error">{err}</p>}
      </div>
    </div>
  );
}
