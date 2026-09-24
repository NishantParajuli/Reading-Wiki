import { useEffect, useState } from "react";
import { acquisitionApi } from "../acquisition/api.js";

export function useSourceAdapter() {
  const [adapters, setAdapters] = useState([]);
  const [adapter, setAdapter] = useState("");
  const [language, setLanguage] = useState("en");
  const [isRaw, setIsRaw] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    acquisitionApi.adapters().then(list => {
      if (!active) return;
      if (!Array.isArray(list) || !list.length) throw new Error("No website sources are available.");
      setAdapters(list);
      setAdapter(list[0].name);
      const language = list[0].default_language || "en";
      setLanguage(language);
      setIsRaw(language !== "en");
    }).catch(error => {
      if (active) setError(error.message || "Could not load website sources.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [attempt]);

  function chooseAdapter(name) {
    const selected = adapters.find(item => item.name === name);
    if (!selected) return;
    const language = selected.default_language || "en";
    setAdapter(name);
    setLanguage(language);
    setIsRaw(language !== "en");
  }

  const selected = adapters.find(item => item.name === adapter);
  return {
    adapters, adapter, chooseAdapter, selected, language, setLanguage, isRaw, setIsRaw,
    loading, error, ready: !loading && !error && !!selected,
    retry: () => setAttempt(value => value + 1),
  };
}
