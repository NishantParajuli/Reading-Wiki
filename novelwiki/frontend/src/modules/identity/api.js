import { API_BASE, delJSON, getJSON, postJSON, postMultipart, req } from "../../shared/api/http.js";

export const authApi = {
  me: () => getJSON(`${API_BASE}/auth/me`),
  login: (identifier, password) => postJSON(`${API_BASE}/auth/login`, { identifier, password }),
  register: (email, username, password) => postJSON(`${API_BASE}/auth/register`, { email, username, password }),
  logout: () => postJSON(`${API_BASE}/auth/logout`, {}),
  requestReset: (email) => postJSON(`${API_BASE}/auth/request-reset`, { email }),
  reset: (token, password) => postJSON(`${API_BASE}/auth/reset`, { token, password }),
  verify: (token) => postJSON(`${API_BASE}/auth/verify`, { token }),
  providers: () => getJSON(`${API_BASE}/auth/providers`),
  oauthStart(provider) { window.location.href = `${API_BASE}/auth/oauth/${provider}/start`; },
  links: () => getJSON(`${API_BASE}/auth/links`),
  changePassword: (currentPassword, newPassword) => postJSON(
    `${API_BASE}/auth/change-password`,
    { current_password: currentPassword || null, new_password: newPassword },
  ),
};

export const identityApi = {
  profile: (username) => getJSON(`${API_BASE}/users/${encodeURIComponent(username)}`),
  updateMe: (body) => req("PATCH", `${API_BASE}/me`, body),
  usage: () => getJSON(`${API_BASE}/me/usage`),
  uploadAvatar(file) {
    const form = new FormData(); form.append("file", file);
    return postMultipart(`${API_BASE}/me/avatar`, form);
  },
};
