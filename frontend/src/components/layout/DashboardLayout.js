import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useAuth } from '../../context/AuthContext';
import { notificationsAPI, activityAPI } from '../../services/api';
import { connectNotificationsStream } from '../../utils/notificationsSSE';
import {
  alertNotification,
  alertNewNotificationsFromPoll,
  unlockNotificationAudio,
} from '../../utils/notificationAlerts';
import { useMarkAllNotificationsRead } from '../../hooks/useMarkAllNotificationsRead';
import {
  LayoutDashboard,
  Users,
  Settings,
  LogOut,
  Menu,
  X,
  Bell,
  ChevronRight,
  ChevronLeft,
  Sun,
  Moon,
  Clock,
  AlertTriangle,
  Phone,
  Calendar,
  BarChart3,
  UserCircle,
  TrendingUp,
  Shield,
  RefreshCw,
  Activity,
  MessageCircle,
} from 'lucide-react';
import {
  getNotificationUrgencyLabel,
  getNotificationUrgencyVariant,
} from '../../constants/badgeVariants';
import { CrmBadge } from '../ui/CrmBadge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../ui/tooltip';

const SIDEBAR_COLLAPSED_KEY = 'sidebar-collapsed';

const DashboardLayout = () => {
  const { user, logout, isImpersonating, exitImpersonation } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true';
    } catch {
      return false;
    }
  });
  const [showNotifications, setShowNotifications] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const knownNotificationIds = useRef(new Set());
  const notificationsInitialized = useRef(false);
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('darkMode');
    return saved !== null ? JSON.parse(saved) : true;
  });

  const isAdmin = user?.role === 'admin';
  const isManager = (user?.role || '').toLowerCase() === 'manager';
  const canSeeEscalations = isAdmin || isManager;

  const navItems = useMemo(() => {
    const adminOnlyPaths = ['/sales-dashboard', '/marketing-dashboard', '/settings'];
    const all = [
      { path: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
      { path: '/my-dashboard', icon: UserCircle, label: 'My Dashboard' },
      { path: '/virtual-customer', icon: Users, label: 'Virtual Customer' },
      { path: '/whatsapp', icon: MessageCircle, label: 'WhatsApp' },
      { path: '/escalation-queue', icon: AlertTriangle, label: 'Escalations' },
      { path: '/notifications', icon: Bell, label: 'Notifications' },
      { path: '/sales-dashboard', icon: BarChart3, label: 'Sales Dashboard' },
      { path: '/marketing-dashboard', icon: TrendingUp, label: 'Marketing' },
      { path: '/settings', icon: Settings, label: 'Settings' },
    ];
    let items = isAdmin
      ? all
      : all.filter((item) => {
          if (adminOnlyPaths.includes(item.path)) return false;
          if (item.path === '/escalation-queue') return canSeeEscalations;
          return true;
        });
    if (user?.is_platform_operator && !isImpersonating) {
      items = [
        ...items,
        { path: '/ops', icon: Shield, label: 'Ops' },
        { path: '/ops/active-status', icon: Activity, label: 'Active Status' },
      ];
    }
    return items;
  }, [isAdmin, canSeeEscalations, user?.is_platform_operator, isImpersonating]);

  const fetchNotifications = useCallback(async () => {
    try {
      const response = await notificationsAPI.getAll();
      const incoming = response.data || [];
      const isInitial = !notificationsInitialized.current;
      const { nextIds } = alertNewNotificationsFromPoll(
        knownNotificationIds.current,
        incoming,
        {
          onView: (leadId) => {
            if (leadId) navigateRef.current(`/lead/${leadId}`);
          },
          isInitialLoad: isInitial,
        }
      );
      knownNotificationIds.current = nextIds;
      notificationsInitialized.current = true;
      setNotifications(incoming);
    } catch (error) {
      console.error('Failed to fetch notifications:', error);
    }
  }, []);

  useEffect(() => {
    const unlock = () => unlockNotificationAudio();
    document.addEventListener('click', unlock, { once: true });
    document.addEventListener('keydown', unlock, { once: true });
    return () => {
      document.removeEventListener('click', unlock);
      document.removeEventListener('keydown', unlock);
    };
  }, []);

  useEffect(() => {
    fetchNotifications();
    // Poll for notifications every 30 seconds (fallback)
    const interval = setInterval(fetchNotifications, 30000);

    // SSE notifications stream (authenticated via fetch headers)
    const stop = connectNotificationsStream({
      url: `${import.meta.env.VITE_BACKEND_URL}/api/notifications/stream`,
      onNotification: (n) => {
        setNotifications((prev) => {
          const id = n?.id;
          if (id && prev.some((x) => x.id === id)) return prev;
          if (id) knownNotificationIds.current.add(id);
          return [n, ...prev].slice(0, 100);
        });
        alertNotification(n, {
          onView: (leadId) => {
            if (leadId) navigateRef.current(`/lead/${leadId}`);
          },
          source: 'sse',
        });
      },
      onError: () => {
        /* keep polling fallback */
      },
    });

    return () => {
      clearInterval(interval);
      stop?.();
    };
  }, [fetchNotifications]);

  // Send heartbeat every 2 minutes
  useEffect(() => {
    const sendHeartbeat = () => {
      activityAPI.heartbeat().catch(() => {});
    };
    sendHeartbeat();
    const hbInterval = setInterval(sendHeartbeat, 120000);
    return () => clearInterval(hbInterval);
  }, []);

  useEffect(() => {
    localStorage.setItem('darkMode', JSON.stringify(darkMode));
    // Apply theme to document
    if (darkMode) {
      document.documentElement.classList.remove('light-mode');
      document.documentElement.classList.add('dark-mode');
    } else {
      document.documentElement.classList.remove('dark-mode');
      document.documentElement.classList.add('light-mode');
    }
  }, [darkMode]);

  const { markAllRead: handleMarkAllRead, busy: markAllBusy } = useMarkAllNotificationsRead({
    getItems: () => notifications,
    setItems: setNotifications,
    refetch: fetchNotifications,
  });

  const handleMarkRead = async (id) => {
    try {
      await notificationsAPI.markRead(id);
      setNotifications((prev) => prev.filter((n) => n.id !== id));
    } catch (error) {
      console.error('Failed to mark notification read:', error);
    }
  };

  const handleLogout = () => {
    logout();
    window.location.href = '/login';
  };

  const toggleDarkMode = () => {
    setDarkMode(!darkMode);
  };

  const toggleSidebarCollapsed = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const renderNavLink = (item, { onNavigate, collapsed = false } = {}) => {
    const link = (
      <NavLink
        to={item.path}
        onClick={onNavigate}
        className={({ isActive }) =>
          `flex items-center transition-all ${
            collapsed ? 'justify-center px-3 py-2.5' : 'gap-3 px-6 py-3'
          } text-sm ${
            isActive
              ? 'text-[#C5A059] bg-[#C5A059]/10 border-r-2 border-[#C5A059]'
              : darkMode
                ? 'text-[#A1A1AA] hover:text-white hover:bg-white/5'
                : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
          }`
        }
        data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, '-')}`}
      >
        <item.icon size={20} strokeWidth={1.5} className="shrink-0" />
        {!collapsed && <span className="truncate">{item.label}</span>}
      </NavLink>
    );

    if (!collapsed) return link;

    return (
      <Tooltip>
        <TooltipTrigger asChild>{link}</TooltipTrigger>
        <TooltipContent side="right">{item.label}</TooltipContent>
      </Tooltip>
    );
  };

  const getNotificationIcon = (type) => {
    switch (type) {
      case 'rnr_followup': return Phone;
      case 'dormant_lead': case 'stale_lead': return Clock;
      case 'task_reminder': case 'task_overdue': return Calendar;
      case 'new_lead_assigned': return AlertTriangle;
      case 'lead_status_changed': return RefreshCw;
      case 'site_visit_reminder': return Calendar;
      case 'campaign_alert': return AlertTriangle;
      default: return AlertTriangle;
    }
  };

  const getUrgencyColor = (n) => {
    const variant = getNotificationUrgencyVariant(n);
    return {
      variant,
      iconClass: `crm-urgency-icon--${variant}`,
      label: getNotificationUrgencyLabel(n),
    };
  };

  const unreadCount = notifications.filter(n => !n.is_read).length;
  const overdueCount = notifications.filter(n => n.is_overdue && !n.is_read).length;

  return (
    <div className={`min-h-screen flex ${darkMode ? 'bg-[#0A0A0A]' : 'bg-gray-100'}`}>
      {/* Sidebar - Desktop */}
      <aside
        className={`hidden lg:flex flex-col fixed h-full border-r transition-[width] duration-200 overflow-hidden ${
          sidebarCollapsed ? 'w-16' : 'w-64'
        } ${darkMode ? 'bg-[#0A0A0A] border-white/10' : 'bg-white border-gray-200'}`}
      >
        <div className={`flex items-center border-b ${sidebarCollapsed ? 'p-3 justify-center' : 'p-4 justify-between'} ${darkMode ? 'border-white/10' : 'border-gray-200'}`}>
          {!sidebarCollapsed && (
            <img
              src="https://cdn.prod.website-files.com/677bb760b33b5fd3ff036767/677bbae243140d29ba5e1fc0_Arihant%20W%20Logo.svg"
              alt="Arihant"
              className={`h-7 ${!darkMode ? 'filter invert' : ''}`}
              data-testid="sidebar-logo"
            />
          )}
          <button
            type="button"
            onClick={toggleSidebarCollapsed}
            className={`p-1.5 rounded-md transition-colors ${darkMode ? 'text-[#A1A1AA] hover:text-white hover:bg-white/10' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'}`}
            data-testid="sidebar-collapse-toggle"
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>

        <TooltipProvider delayDuration={200}>
          <nav className="flex-1 py-4 overflow-y-auto overflow-x-hidden">
            {navItems.map((item) => (
              <React.Fragment key={item.path}>
                {renderNavLink(item, { collapsed: sidebarCollapsed })}
              </React.Fragment>
            ))}
          </nav>
        </TooltipProvider>

        <div className={`border-t ${sidebarCollapsed ? 'p-2' : 'p-3'} ${darkMode ? 'border-white/10' : 'border-gray-200'}`}>
          {!sidebarCollapsed ? (
            <>
              <div className="flex items-center gap-2 px-1 py-2">
                <div className="w-8 h-8 rounded-full bg-[#C5A059] flex items-center justify-center text-black text-sm font-medium shrink-0">
                  {user?.full_name?.charAt(0) || 'R'}
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`text-sm truncate ${darkMode ? 'text-white' : 'text-gray-900'}`}>{user?.full_name || 'User'}</p>
                  <p className={`text-[10px] truncate ${darkMode ? 'text-[#52525B]' : 'text-gray-500'}`}>{user?.email}</p>
                </div>
              </div>
              <button
                onClick={handleLogout}
                className={`w-full flex items-center gap-2 px-2 py-2 text-sm ${darkMode ? 'text-[#A1A1AA]' : 'text-gray-600'} hover:text-red-500 transition-colors`}
                data-testid="logout-btn"
              >
                <LogOut size={16} strokeWidth={1.5} />
                Sign Out
              </button>
            </>
          ) : (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={handleLogout}
                    className={`w-full flex items-center justify-center p-2 rounded-md ${darkMode ? 'text-[#A1A1AA]' : 'text-gray-600'} hover:text-red-500 transition-colors`}
                    data-testid="logout-btn"
                    aria-label="Sign out"
                  >
                    <LogOut size={18} strokeWidth={1.5} />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">Sign Out</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </div>
      </aside>

      {/* Mobile Sidebar */}
      <motion.aside
        className={`lg:hidden fixed inset-y-0 left-0 z-50 w-64 ${darkMode ? 'bg-[#0A0A0A] border-white/10' : 'bg-white border-gray-200'} border-r ${
          sidebarOpen ? 'block' : 'hidden'
        }`}
        initial={{ x: -256 }}
        animate={{ x: sidebarOpen ? 0 : -256 }}
        transition={{ duration: 0.2 }}
      >
        {/* Close Button */}
        <button
          onClick={() => setSidebarOpen(false)}
          className={`absolute top-4 right-4 ${darkMode ? 'text-[#A1A1AA] hover:text-white' : 'text-gray-400 hover:text-gray-600'}`}
          data-testid="close-sidebar-btn"
        >
          <X size={24} />
        </button>

        {/* Logo */}
        <div className={`p-6 border-b ${darkMode ? 'border-white/10' : 'border-gray-200'}`}>
          <img
            src="https://cdn.prod.website-files.com/677bb760b33b5fd3ff036767/677bbae243140d29ba5e1fc0_Arihant%20W%20Logo.svg"
            alt="Arihant"
            className={`h-8 ${!darkMode ? 'filter invert' : ''}`}
          />
        </div>

        {/* Navigation */}
        <nav className="py-6">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-6 py-3 text-sm transition-all ${
                  isActive
                    ? 'text-[#C5A059] bg-[#C5A059]/10 border-r-2 border-[#C5A059]'
                    : darkMode 
                      ? 'text-[#A1A1AA] hover:text-white hover:bg-white/5'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                }`
              }
            >
              <item.icon size={20} strokeWidth={1.5} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* User Section */}
        <div className={`absolute bottom-0 left-0 right-0 p-4 border-t ${darkMode ? 'border-white/10' : 'border-gray-200'}`}>
          <button
            onClick={handleLogout}
            className={`w-full flex items-center gap-3 px-4 py-2 text-sm ${darkMode ? 'text-[#A1A1AA]' : 'text-gray-600'} hover:text-red-500 transition-colors`}
          >
            <LogOut size={18} strokeWidth={1.5} />
            Sign Out
          </button>
        </div>
      </motion.aside>

      {/* Mobile Overlay */}
      {sidebarOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black/50 z-40"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Main Content */}
      <main className={`flex-1 min-w-0 transition-[margin] duration-200 ${sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'}`}>
        {isImpersonating && (
          <div
            className="sticky top-0 z-40 flex items-center justify-between gap-4 px-4 lg:px-8 py-2 bg-amber-500/15 border-b border-amber-500/30"
            data-testid="impersonation-banner"
          >
            <p className="text-amber-400 text-sm">
              Viewing as <span className="font-medium text-white">{user?.full_name}</span>
            </p>
            <button
              type="button"
              onClick={() => exitImpersonation().then(() => navigate('/ops'))}
              className="text-xs font-medium px-3 py-1.5 rounded-md bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 transition-colors"
              data-testid="exit-impersonation-btn"
            >
              Exit impersonation
            </button>
          </div>
        )}
        {/* Top Bar */}
        <header className={`sticky top-0 z-30 ${darkMode ? 'bg-[#0A0A0A]/80' : 'bg-white/80'} backdrop-blur-xl border-b ${darkMode ? 'border-white/10' : 'border-gray-200'}`}>
          <div className="flex items-center justify-between px-3 lg:px-4 py-3">
            {/* Mobile Menu Button */}
            <button
              onClick={() => setSidebarOpen(true)}
              className={`lg:hidden ${darkMode ? 'text-[#A1A1AA] hover:text-white' : 'text-gray-400 hover:text-gray-600'}`}
              data-testid="open-sidebar-btn"
            >
              <Menu size={24} />
            </button>

            {/* Breadcrumb */}
            <div className="hidden lg:flex items-center gap-2 text-sm">
              <span className={darkMode ? 'text-[#52525B]' : 'text-gray-400'}>Home</span>
              <ChevronRight size={14} className={darkMode ? 'text-[#52525B]' : 'text-gray-400'} />
              <span className="text-[#C5A059] capitalize">
                {location.pathname.split('/')[1] || 'Dashboard'}
              </span>
            </div>

            {/* Right Section */}
            <div className="flex items-center gap-4">
              {/* Dark/Light Mode Toggle */}
              <button
                onClick={toggleDarkMode}
                className={`p-2 rounded-lg transition-colors ${darkMode ? 'text-[#A1A1AA] hover:text-white hover:bg-white/10' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'}`}
                data-testid="theme-toggle-btn"
                title={darkMode ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
              >
                {darkMode ? <Sun size={20} strokeWidth={1.5} /> : <Moon size={20} strokeWidth={1.5} />}
              </button>

              {/* Notifications */}
              <div className="relative">
                <button
                  onClick={() => setShowNotifications(!showNotifications)}
                  className={`relative p-2 rounded-lg transition-colors ${darkMode ? 'text-[#A1A1AA] hover:text-white hover:bg-white/10' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'}`}
                  data-testid="notifications-btn"
                >
                  <Bell size={20} strokeWidth={1.5} />
                  {overdueCount > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-[10px] text-white flex items-center justify-center font-medium">
                      {overdueCount > 9 ? '9+' : overdueCount}
                    </span>
                  )}
                  {unreadCount > 0 && (
                    <span className="absolute top-0 right-0 w-5 h-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">
                      {unreadCount > 9 ? '9+' : unreadCount}
                    </span>
                  )}
                </button>

                {/* Notifications Panel */}
                <AnimatePresence>
                  {showNotifications && (
                    <motion.div
                      initial={{ opacity: 0, y: 10, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 10, scale: 0.95 }}
                      className={`absolute right-0 mt-2 w-80 ${darkMode ? 'bg-[#1A1A1A] border-white/10' : 'bg-white border-gray-200'} border rounded-lg shadow-xl overflow-hidden z-50`}
                      data-testid="notifications-panel"
                    >
                      <div className={`px-4 py-3 border-b ${darkMode ? 'border-white/10' : 'border-gray-200'} flex items-center justify-between`}>
                        <div>
                          <h3 className={`font-medium ${darkMode ? 'text-white' : 'text-gray-900'}`}>Notifications</h3>
                          <p className={`text-xs ${darkMode ? 'text-[#52525B]' : 'text-gray-500'}`}>
                            {unreadCount} unread
                          </p>
                        </div>
                        {unreadCount > 0 && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleMarkAllRead();
                            }}
                            disabled={markAllBusy}
                            className={`text-xs hover:underline ${markAllBusy ? 'opacity-60 cursor-not-allowed text-[#A1A1AA]' : 'text-[#C5A059]'}`}
                            data-testid="mark-all-read-btn"
                          >
                            {markAllBusy ? 'Clearing…' : 'Mark all read'}
                          </button>
                        )}
                      </div>
                      
                      <div className="max-h-96 overflow-y-auto">
                        {notifications.length === 0 ? (
                          <div className="p-8 text-center">
                            <Bell className={`mx-auto ${darkMode ? 'text-[#52525B]' : 'text-gray-300'}`} size={32} />
                            <p className={`mt-2 text-sm ${darkMode ? 'text-[#52525B]' : 'text-gray-500'}`}>
                              No pending notifications
                            </p>
                          </div>
                        ) : (
                          notifications.slice(0, 20).map((notification, idx) => {
                            const IconComponent = getNotificationIcon(notification.type);
                            const urgency = getUrgencyColor(notification);
                            return (
                              <div
                                key={notification.id || idx}
                                onClick={() => {
                                  handleMarkRead(notification.id);
                                  if (notification.lead_id) window.location.href = `/lead/${notification.lead_id}`;
                                }}
                                className={`px-4 py-3 border-b ${darkMode ? 'border-white/5 hover:bg-white/5' : 'border-gray-100 hover:bg-gray-50'} cursor-pointer transition-colors ${!notification.is_read ? (darkMode ? 'bg-white/[0.02]' : 'bg-blue-50/50') : ''}`}
                                data-testid={`notification-${idx}`}
                              >
                                <div className="flex items-start gap-3">
                                  <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${urgency.iconClass}`}>
                                    <IconComponent size={14} />
                                  </div>
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                      <p className={`text-sm font-medium truncate ${darkMode ? 'text-white' : 'text-gray-900'}`}>
                                        {notification.title || notification.lead_name}
                                      </p>
                                      {!notification.is_read && <span className="w-2 h-2 rounded-full bg-[#C5A059] flex-shrink-0" />}
                                    </div>
                                    <p className={`text-xs ${darkMode ? 'text-[#A1A1AA]' : 'text-gray-600'} mt-0.5 line-clamp-2`}>
                                      {notification.message}
                                    </p>
                                    <CrmBadge variant={urgency.variant} size="xs" uppercase className="mt-1">
                                      {urgency.label}
                                    </CrmBadge>
                                  </div>
                                </div>
                              </div>
                            );
                          })
                        )}
                      </div>

                      {notifications.length > 0 && (
                        <div className={`px-4 py-2 border-t ${darkMode ? 'border-white/10' : 'border-gray-200'}`}>
                          <button
                            type="button"
                            onClick={() => { setShowNotifications(false); navigate('/notifications'); }}
                            className="text-[#C5A059] text-sm hover:underline w-full text-center"
                          >
                            View All Alerts
                          </button>
                        </div>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* User Avatar - Mobile */}
              <div className="lg:hidden w-8 h-8 rounded-full bg-[#C5A059] flex items-center justify-center text-black text-sm font-medium">
                {user?.full_name?.charAt(0) || 'R'}
              </div>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <div className="p-3 lg:p-4 min-w-0">
          <TooltipProvider delayDuration={200}>
            <Outlet />
          </TooltipProvider>
        </div>
      </main>

      {/* Close notifications when clicking outside */}
      {showNotifications && (
        <div 
          className="fixed inset-0 z-40" 
          onClick={() => setShowNotifications(false)}
        />
      )}
    </div>
  );
};

export default DashboardLayout;
