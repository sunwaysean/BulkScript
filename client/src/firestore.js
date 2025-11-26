// src/firestore.js
import {
  collection,
  addDoc,
  query,
  orderBy,
  onSnapshot,
  getDocs,
  getDoc,
  doc,
  serverTimestamp,
  deleteDoc,
  updateDoc
} from "firebase/firestore";
import { db } from "./firebase";

// Save a session (FULL payload explicitly defined)
export const saveSessionForUser = async (uid, session) => {
  const col = collection(db, "users", uid, "history");

  const payload = {
    title: session.title,
    urls: session.urls || [],
    videos: session.videos || [],           // REQUIRED for reload
    transcript: session.transcript || "",
    analysis: session.analysis || "",
    createdAt: serverTimestamp(),
  };

  const ref = await addDoc(col, payload);
  return ref.id;
};

// Update an existing session document
export const updateSession = async (uid, sessionId, session) => {
  const ref = doc(db, "users", uid, "history", sessionId);
  const payload = {
    title: session.title,
    urls: session.urls || [],
    videos: session.videos || [],
    transcript: session.transcript || "",
    analysis: session.analysis || "",
    // don't overwrite createdAt; provide an updatedAt to denote edits
    updatedAt: serverTimestamp()
  };
  await updateDoc(ref, payload);
};

// Real-time history listener
export const listenUserHistory = (uid, callback) => {
  const col = collection(db, "users", uid, "history");
  const q = query(col, orderBy("createdAt", "desc"));

  // Use onSnapshot with an error handler; on error, fallback to a one-time getDocs
  const unsub = onSnapshot(
    q,
    (snap) => {
      const items = snap.docs.map((d) => {
        const data = d.data();
        return {
          id: d.id,
          ...data,
          createdAt: data.createdAt?.toDate() || null
        };
      });
      callback(items);
    },
    async (err) => {
      console.warn('listenUserHistory: realtime listener failed, falling back to getDocs', err);
      try {
        const snap = await getDocs(q);
        const items = snap.docs.map((d) => {
          const data = d.data();
          return {
            id: d.id,
            ...data,
            createdAt: data.createdAt?.toDate() || null
          };
        });
        callback(items);
      } catch (e) {
        console.error('listenUserHistory: fallback getDocs failed', e);
        callback([]);
      }
    }
  );

  return unsub;
};

// One-time fetch helper (useful for diagnostics / fallbacks)
export const fetchUserHistoryOnce = async (uid) => {
  const col = collection(db, "users", uid, "history");
  const q = query(col, orderBy("createdAt", "desc"));
  const snap = await getDocs(q);
  return snap.docs.map((d) => {
    const data = d.data();
    return {
      id: d.id,
      ...data,
      createdAt: data.createdAt?.toDate() || null
    };
  });
};

// Load a single session
export const getSession = async (uid, sessionId) => {
  const ref = doc(db, "users", uid, "history", sessionId);
  const snap = await getDoc(ref);
  if (!snap.exists()) return null;

  const data = snap.data();
  return {
    id: snap.id,
    ...data,
    createdAt: data.createdAt?.toDate() || null
  };
};

// Delete session
export const deleteSession = async (uid, sessionId) => {
  const ref = doc(db, "users", uid, "history", sessionId);
  await deleteDoc(ref);
};
