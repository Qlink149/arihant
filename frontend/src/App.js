import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth, getPostLoginPath } from './context/AuthContext';
import { Toaster } from './components/ui/sonner';

import LoginPage from './pages/LoginPage';
import DashboardLayout from './components/layout/DashboardLayout';
import RouteProgress from './components/layout/RouteProgress';

const PageLoading = () => (
  <div className="min-h-[40vh] flex items-center justify-center">
    <div className="text-[#C5A059] animate-pulse">Loading...</div>
  </div>
);

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const VirtualCustomerPage = lazy(() => import('./pages/VirtualCustomerPage'));
const DigitalTwinPage = lazy(() => import('./pages/DigitalTwinPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const SalesDashboardPage = lazy(() => import('./pages/SalesDashboardPage'));
const MyDashboardPage = lazy(() => import('./pages/MyDashboardPage'));
const MarketingDashboardPage = lazy(() => import('./pages/MarketingDashboardPage'));
const NotificationsPage = lazy(() => import('./pages/NotificationsPage'));
const WhatsAppInboxPage = lazy(() => import('./pages/WhatsAppInboxPage'));
const EscalationQueuePage = lazy(() => import('./pages/EscalationQueuePage'));
const PlatformOpsPage = lazy(() => import('./pages/PlatformOpsPage'));
const OpsActiveStatusPage = lazy(() => import('./pages/OpsActiveStatusPage'));

const LazyPage = ({ children }) => (
  <Suspense fallback={<PageLoading />}>{children}</Suspense>
);

// Protected Route Component
const ProtectedRoute = ({ children }) => {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-crm flex items-center justify-center">
        <div className="text-[#C5A059] animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
};

const AdminRoute = ({ children }) => {
  const { isAuthenticated, loading, user } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-crm flex items-center justify-center">
        <div className="text-[#C5A059] animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (user?.role !== 'admin') {
    return <Navigate to="/my-dashboard" replace />;
  }

  return children;
};

/** Admin or manager — Escalation Queue (matches GET /escalations). */
const AdminOrManagerRoute = ({ children }) => {
  const { isAuthenticated, loading, user } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-crm flex items-center justify-center">
        <div className="text-[#C5A059] animate-pulse">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  const role = (user?.role || '').toLowerCase();
  if (role !== 'admin' && role !== 'manager') {
    return <Navigate to="/my-dashboard" replace />;
  }

  return children;
};

// Public Route Component (redirects to dashboard if logged in)
const PublicRoute = ({ children }) => {
  const { isAuthenticated, loading, user } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-crm flex items-center justify-center">
        <div className="text-[#C5A059] animate-pulse">Loading...</div>
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to={getPostLoginPath(user)} replace />;
  }

  return children;
};

function AppRoutes() {
  const { user } = useAuth();

  return (
    <>
      <RouteProgress />
      <Routes>
      {/* Public Routes */}
      <Route
        path="/login"
        element={
          <PublicRoute>
            <LoginPage />
          </PublicRoute>
        }
      />

      {/* Protected Routes */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DashboardLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<LazyPage><DashboardPage /></LazyPage>} />
        <Route path="virtual-customer" element={<LazyPage><VirtualCustomerPage /></LazyPage>} />
        <Route path="virtual-dashboard" element={<Navigate to="/virtual-customer" replace />} />
        <Route path="lead/:leadId" element={<LazyPage><DigitalTwinPage /></LazyPage>} />
        <Route path="settings" element={<AdminRoute><LazyPage><SettingsPage /></LazyPage></AdminRoute>} />
        <Route path="sales-dashboard" element={<AdminRoute><LazyPage><SalesDashboardPage /></LazyPage></AdminRoute>} />
        <Route path="my-dashboard" element={<LazyPage><MyDashboardPage /></LazyPage>} />
        <Route path="marketing-dashboard" element={<AdminRoute><LazyPage><MarketingDashboardPage /></LazyPage></AdminRoute>} />
        <Route path="notifications" element={<LazyPage><NotificationsPage /></LazyPage>} />
        <Route path="whatsapp" element={<LazyPage><WhatsAppInboxPage /></LazyPage>} />
        <Route
          path="escalation-queue"
          element={
            <AdminOrManagerRoute>
              <LazyPage>
                <EscalationQueuePage />
              </LazyPage>
            </AdminOrManagerRoute>
          }
        />
        {user?.is_platform_operator && (
          <>
            <Route path="ops" element={<LazyPage><PlatformOpsPage /></LazyPage>} />
            <Route path="ops/active-status" element={<LazyPage><OpsActiveStatusPage /></LazyPage>} />
          </>
        )}
      </Route>

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
    </>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
        <Toaster />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
