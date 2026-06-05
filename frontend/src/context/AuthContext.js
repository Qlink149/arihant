import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { platformOpsAPI } from '../services/api';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const OPERATOR_TOKEN_KEY = 'platform_operator_token';
const OPERATOR_REFRESH_KEY = 'platform_operator_refresh_token';

const AuthContext = createContext(null);

export const getPostLoginPath = (user) =>
  user?.role === 'admin' ? '/dashboard' : '/my-dashboard';

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [loading, setLoading] = useState(!!localStorage.getItem('token'));
  const [isImpersonating, setIsImpersonating] = useState(
    () => !!localStorage.getItem(OPERATOR_TOKEN_KEY)
  );

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem(OPERATOR_TOKEN_KEY);
    localStorage.removeItem(OPERATOR_REFRESH_KEY);
    setToken(null);
    setUser(null);
    setIsImpersonating(false);
    delete axios.defaults.headers.common['Authorization'];
  }, []);

  const fetchUser = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/auth/me`);
      setUser(response.data);
    } catch (error) {
      console.error('Failed to fetch user:', error);
      logout();
    } finally {
      setLoading(false);
    }
  }, [logout]);

  const hydrateSession = useCallback(async (accessToken, refreshToken) => {
    localStorage.setItem('token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    axios.defaults.headers.common['Authorization'] = `Bearer ${accessToken}`;
    const me = await axios.get(`${API}/auth/me`);
    setUser(me.data);
    setToken(accessToken);
    setLoading(false);
    return me.data;
  }, []);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setLoading(false);
      delete axios.defaults.headers.common['Authorization'];
      return;
    }
    axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    if (!user) {
      fetchUser();
    } else {
      setLoading(false);
    }
  }, [token, user, fetchUser]);

  const applySessionTokens = (accessToken, refreshToken) => {
    localStorage.setItem('token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    setToken(accessToken);
    axios.defaults.headers.common['Authorization'] = `Bearer ${accessToken}`;
  };

  const login = async (email, password) => {
    const formData = new URLSearchParams();
    formData.append('username', email);
    formData.append('password', password);

    try {
      const response = await axios.post(`${API}/auth/login`, formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });

      const { access_token, refresh_token } = response.data;
      localStorage.removeItem(OPERATOR_TOKEN_KEY);
      localStorage.removeItem(OPERATOR_REFRESH_KEY);
      setIsImpersonating(false);
      const me = await hydrateSession(access_token, refresh_token);
      return me;
    } catch (error) {
      logout();
      throw error;
    }
  };

  const impersonateUser = async (userId) => {
    const operatorToken = localStorage.getItem('token');
    const operatorRefresh = localStorage.getItem('refresh_token');
    if (!operatorToken) {
      throw new Error('Not authenticated');
    }

    const { data } = await platformOpsAPI.impersonate(userId);

    if (!localStorage.getItem(OPERATOR_TOKEN_KEY)) {
      localStorage.setItem(OPERATOR_TOKEN_KEY, operatorToken);
      localStorage.setItem(OPERATOR_REFRESH_KEY, operatorRefresh || '');
    }

    setIsImpersonating(true);
    return hydrateSession(data.access_token, data.refresh_token);
  };

  const exitImpersonation = async () => {
    const operatorToken = localStorage.getItem(OPERATOR_TOKEN_KEY);
    const operatorRefresh = localStorage.getItem(OPERATOR_REFRESH_KEY);

    if (!operatorToken) {
      setIsImpersonating(false);
      return;
    }

    localStorage.removeItem(OPERATOR_TOKEN_KEY);
    localStorage.removeItem(OPERATOR_REFRESH_KEY);
    setIsImpersonating(false);
    return hydrateSession(operatorToken, operatorRefresh || '');
  };

  const value = {
    user,
    token,
    loading,
    login,
    logout,
    applySessionTokens,
    impersonateUser,
    exitImpersonation,
    isImpersonating,
    isAuthenticated: !!token && !!user
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

export default AuthContext;
