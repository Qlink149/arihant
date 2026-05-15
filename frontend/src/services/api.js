import axios from 'axios';
import { toast } from 'sonner';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Create axios instance
const api = axios.create({
  baseURL: API,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Add token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      
      try {
        const refreshToken = localStorage.getItem('refresh_token');
        const response = await axios.post(`${API}/auth/refresh`, { refresh_token: refreshToken });
        const { access_token } = response.data;
        
        localStorage.setItem('token', access_token);
        api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
        originalRequest.headers['Authorization'] = `Bearer ${access_token}`;
        
        return api(originalRequest);
      } catch (refreshError) {
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        window.location.href = '/login';
        return Promise.reject(refreshError);
      }
    }

    const cfg = originalRequest || {};
    const skipGlobal = cfg.skipGlobalErrorToast === true;

    if (!skipGlobal && !error.response) {
      toast.error(
        'Cannot reach API. Check that the backend is running and REACT_APP_BACKEND_URL is set correctly.'
      );
    }

    return Promise.reject(error);
  }
);

// Auth API
export const authAPI = {
  login: (email, password) => {
    const formData = new URLSearchParams();
    formData.append('username', email);
    formData.append('password', password);
    return api.post('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    });
  },
  register: (data) => api.post('/auth/register', data),
  getMe: () => api.get('/auth/me'),
  changePassword: (data) => api.put('/auth/password', data),
};

// Leads API
export const leadsAPI = {
  getAll: (params) => api.get('/leads', { params }),
  getOne: (id) => api.get(`/leads/${id}`),
  create: (data) => api.post('/leads', data),
  update: (id, data) => api.put(`/leads/${id}`, data),
  uploadCSV: (file, replaceAll = false) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/leads/upload-csv?replace_all=${replaceAll}`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
  },
  merge: (primaryId, duplicateId) => api.post(`/leads/${primaryId}/merge/${duplicateId}`),
  addCallSummary: (id, data) => api.post(`/leads/${id}/call-summary`, data),
  addContext: (id, data) => api.post(`/leads/${id}/context`, data),
  addTask: (id, data) => api.post(`/leads/${id}/tasks`, data),
  getSuggestions: (id) => api.get(`/leads/${id}/suggestions`),
  autoAssign: (id) => api.post('/leads/auto-assign', null, { params: { lead_id: id } })
};

// Tasks API
export const tasksAPI = {
  getAll: (params) => api.get('/tasks', { params }),
  create: (data) => api.post('/tasks', data),
  update: (id, data) => api.put(`/tasks/${id}`, data)
};

// Notifications API
export const notificationsAPI = {
  getAll: (params) => api.get('/notifications', { params }),
  markRead: (id) => api.put(`/notifications/${id}/read`),
  markAllRead: () => api.put('/notifications/read-all')
};

// Analytics API
export const analyticsAPI = {
  getDashboard: (params) => api.get('/analytics/dashboard', { params }),
  getSalesDashboard: () => api.get('/analytics/sales-dashboard'),
  getSalesRepLeads: (name, params) =>
    api.get('/analytics/sales-dashboard/rep-leads', { params: { name, ...params } }),
};

// Assignment Rules API
export const assignmentAPI = {
  getRules: () => api.get('/assignment-rules'),
  createRule: (data) => api.post('/assignment-rules', data)
};

// Alerts API
export const alertsAPI = {
  getConfig: () => api.get('/alerts/config'),
  createConfig: (data) => api.post('/alerts/config', data),
  getPending: () => api.get('/alerts/pending')
};

// WhatsApp API
export const whatsappAPI = {
  getTemplates: () => api.get('/whatsapp/templates'),
  sendMessage: (data) => api.post('/whatsapp/send', data),
  sendToLead: (leadId, data) => api.post(`/whatsapp/send-to-lead/${leadId}`, data),
  getChatHistory: (phone) => api.get(`/whatsapp/chat-history/${phone}`),
  getLeadChat: (leadId) => api.get(`/whatsapp/lead-chat/${leadId}`),
  setupWebhook: () => api.post('/integrations/gupshup/setup-webhook'),
  getSubscriptions: () => api.get('/integrations/gupshup/subscriptions'),
  getWebhookStatus: () => api.get('/integrations/gupshup/webhook-status')
};

// My Dashboard / Activity API
export const activityAPI = {
  heartbeat: () => api.post('/activity/heartbeat'),
  setStatus: (status, userId) => api.put('/activity/status', null, { params: { status, user_id: userId } }),
  getTeamStatus: () => api.get('/activity/team-status'),
};

export const platformOpsAPI = {
  listUsers: () => api.get('/ops/users'),
  impersonate: (userId) => api.post('/ops/impersonate', { user_id: userId }),
};

export const myDashboardAPI = {
  getData: () => api.get('/my-dashboard'),
  getLeads: (params) => api.get('/my-dashboard/leads', { params }),
  transferLead: (data) => api.post('/leads/transfer', data),
  acknowledgeTransfer: (transferId) => api.put(`/leads/transfer/${transferId}/acknowledge`),
  getReps: () => api.get('/activity/team-status'),
};

// Marketing API
export const marketingAPI = {
  addSpend: (data) => api.post('/marketing/spends', data),
  getSpends: (params) => api.get('/marketing/spends', { params }),
  getDashboard: () => api.get('/marketing/dashboard'),
  deleteSpend: (id) => api.delete(`/marketing/spends/${id}`),
};

// Reminders API
export const remindersAPI = {
  getRules: () => api.get('/reminders/rules'),
  updateRule: (id, data) => api.put(`/reminders/rules/${id}`, data),
  getHistory: (limit = 50) => api.get('/reminders/history', { params: { limit } }),
  triggerNow: () => api.post('/reminders/trigger'),
  sendManual: (data) => api.post('/reminders/send', data),
};

export default api;
