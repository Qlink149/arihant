import React, { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { analyticsAPI } from '../services/api';
import {
  Users,
  Crown,
  Flame,
  CheckCircle,
  Snowflake,
  TrendingUp,
  TrendingDown,
  Calendar,
  ChevronDown,
  Info,
  Building,
  Layers
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell
} from 'recharts';
import { Button } from '../components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { Calendar as CalendarUI } from '../components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '../components/ui/popover';
import {
  Tooltip as TooltipUI,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../components/ui/tooltip';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '../components/ui/dialog';

// Tooltip copy aligned with GET /api/analytics/dashboard counts
const LEAD_CRITERIA = {
  cold: {
    title: "Cold leads (API: cold_leads)",
    rules: [
      'Temperature field matches "Cold" (case-insensitive).'
    ]
  },
  dormant: {
    title: "Dormant leads (API: dormant_leads)",
    rules: [
      "No meaningful activity for 7+ days (uses updated_at_dt / updated_at, then created dates for legacy rows).",
      "Excludes leads whose status is exactly Won, Lost, Advance Paid, Closed, Booked, Dropped, or Unqualified (case-insensitive)."
    ]
  },
  hot: {
    title: "Hot leads (API: hot_leads)",
    rules: [
      'Temperature field matches "Hot" (case-insensitive; same for warm/cold counts on the server).'
    ]
  },
  warm: {
    title: "Warm leads (API: warm_leads)",
    rules: [
      'Temperature field matches "Warm" (case-insensitive).'
    ]
  },
  qualified: {
    title: "Qualified leads (API: qualified_leads)",
    rules: [
      'lead_status matches "qualified" anywhere in the string (case-insensitive regex on the server).'
    ]
  },
  vip: {
    title: "VIP pipeline (API: vip_leads)",
    rules: [
      "vip flag is true on the lead document (budget / VIP rules evaluated server-side)."
    ]
  }
};

// Regional colors - more distinct and accessible
const REGIONAL_COLORS = [
  { bg: 'rgba(59, 130, 246, 0.2)', border: 'rgba(59, 130, 246, 0.5)', text: '#3B82F6' },   // Blue
  { bg: 'rgba(16, 185, 129, 0.2)', border: 'rgba(16, 185, 129, 0.5)', text: '#10B981' },   // Emerald
  { bg: 'rgba(245, 158, 11, 0.2)', border: 'rgba(245, 158, 11, 0.5)', text: '#F59E0B' },   // Amber
  { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.5)', text: '#EF4444' },     // Red
  { bg: 'rgba(168, 85, 247, 0.2)', border: 'rgba(168, 85, 247, 0.5)', text: '#A855F7' },   // Purple
  { bg: 'rgba(236, 72, 153, 0.2)', border: 'rgba(236, 72, 153, 0.5)', text: '#EC4899' },   // Pink
  { bg: 'rgba(20, 184, 166, 0.2)', border: 'rgba(20, 184, 166, 0.5)', text: '#14B8A6' },   // Teal
  { bg: 'rgba(99, 102, 241, 0.2)', border: 'rgba(99, 102, 241, 0.5)', text: '#6366F1' },   // Indigo
];

// Project images from Arihant Spaces (mapped to real project names)
const PROJECT_IMAGES = {
  'ECR - Reserve 16': 'https://cdn.prod.website-files.com/677bb760b33b5fd3ff036767/67e2c0a4eb6a6eb33f5d2f0a_Reserve%2016%20-%20Card.webp',
  'Abhiramapuram - Krishna': 'https://cdn.prod.website-files.com/677bb760b33b5fd3ff036767/67e2c0a457ef00ce4f81c2ae_Krsna%20-%20Card.webp',
  'OMR - Vivriti': 'https://cdn.prod.website-files.com/677bb760b33b5fd3ff036767/67e2c0a4b2eaeb59d0cce6f9_Vivriti%20-%20Card.webp',
  'Saligramam Melange': 'https://cdn.prod.website-files.com/677bb760b33b5fd3ff036767/67e2c0a4dcfb8e9e1b2d5f76_Melange%20-%20Card.webp',
  // Placeholder card art (same CDN pattern as other projects until a Kilpauk asset is available)
  'Flowers Road - Kilpauk': 'https://cdn.prod.website-files.com/677bb760b33b5fd3ff036767/67e2c0a4dcfb8e9e1b2d5f76_Melange%20-%20Card.webp'
};

const DashboardPage = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [timeFilter, setTimeFilter] = useState('all');
  const [projectFilter, setProjectFilter] = useState('all');
  const [dateRange, setDateRange] = useState(null);
  const [otherModalOpen, setOtherModalOpen] = useState(false);

  const timeFilters = [
    { value: '7', label: '7 Days' },
    { value: '15', label: '15 Days' },
    { value: '30', label: '30 Days' },
    { value: 'all', label: 'All Time' },
    { value: 'custom', label: 'Custom Range' }
  ];

  // Dynamic project list from API data
  const projects = (analytics?.projects || []).map(p => p.name).filter(n => n !== 'Unknown');

  useEffect(() => {
    fetchAnalytics();
  }, [timeFilter]);

  const fetchAnalytics = async () => {
    try {
      const params = {};
      if (timeFilter !== 'all' && timeFilter !== 'custom') {
        params.days = parseInt(timeFilter);
      }
      const response = await analyticsAPI.getDashboard(params);
      setAnalytics(response.data);
    } catch (error) {
      console.error('Failed to fetch analytics:', error);
    } finally {
      setLoading(false);
    }
  };

  // Navigate to Virtual Customer with project filter
  const handleProjectClick = (projectName) => {
    navigate(`/virtual-customer?project=${encodeURIComponent(projectName)}`);
  };

  const { topProjects, otherProjects, otherTotal, maxProjectCount } = useMemo(() => {
    const all = analytics?.projects || [];
    const top = all.slice(0, 11);
    const other = all.slice(11);
    const max = Math.max(...all.map((p) => p.count), 1);
    const total = other.reduce((sum, p) => sum + p.count, 0);
    return {
      topProjects: top,
      otherProjects: other,
      otherTotal: total,
      maxProjectCount: max,
    };
  }, [analytics?.projects]);

  const handleOtherProjectClick = (projectName) => {
    setOtherModalOpen(false);
    handleProjectClick(projectName);
  };

  const COLORS = ['#059669', '#D97706', '#DC2626', '#3B82F6', '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#6366F1', '#EF4444', '#10B981', '#A855F7', '#F59E0B', '#06B6D4'];

  // Use real status breakdown from API
  const statusData = analytics?.status_breakdown
    ? analytics.status_breakdown.slice(0, 8).map((s, idx) => ({
        name: s.name,
        value: s.count,
        color: COLORS[idx % COLORS.length]
      }))
    : [];

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-[#1A1A1A] border border-white/10 rounded-lg p-3 shadow-xl">
          <p className="text-[#C5A059] font-medium">{label}</p>
          <p className="text-white">{payload[0].value} leads</p>
        </div>
      );
    }
    return null;
  };

  // Info tooltip component for lead categories
  const LeadCriteriaTooltip = ({ type }) => {
    const criteria = LEAD_CRITERIA[type];
    if (!criteria) return null;

    return (
      <TooltipProvider>
        <TooltipUI>
          <TooltipTrigger asChild>
            <button className="ml-2 text-[#52525B] hover:text-[#C5A059] transition-colors">
              <Info size={16} />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right" className="bg-[#1A1A1A] border-white/10 p-4 max-w-xs">
            <p className="text-[#C5A059] font-medium mb-2">{criteria.title}</p>
            <ul className="space-y-1">
              {criteria.rules.map((rule, idx) => (
                <li key={idx} className="text-[#A1A1AA] text-xs flex items-start gap-2">
                  <span className="text-[#C5A059] mt-0.5">•</span>
                  {rule}
                </li>
              ))}
            </ul>
          </TooltipContent>
        </TooltipUI>
      </TooltipProvider>
    );
  };

  if (loading) {
    return (
      <div className="space-y-6 p-2 max-w-6xl mx-auto">
        <div className="h-40 rounded-xl bg-white/5 animate-pulse" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <div key={i} className="h-24 rounded-lg bg-white/5 animate-pulse" />
          ))}
        </div>
        <div className="h-64 rounded-lg bg-white/5 animate-pulse" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Hero Banner */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="relative rounded-xl overflow-hidden h-40 md:h-48"
        data-testid="hero-banner"
      >
        <img
          src="https://images.unsplash.com/photo-1758448511648-d7d8e1993c3f?crop=entropy&cs=srgb&fm=jpg&ixlib=rb-4.1.0&q=85&w=1920&h=400&fit=crop"
          alt="Luxury property"
          className="absolute inset-0 w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-black/80 via-black/60 to-black/30" />
        <div className="relative z-10 h-full flex items-center px-8">
          <div>
            <p className="text-[#C5A059] text-sm font-medium tracking-widest uppercase">Arihant Spaces</p>
            <h1 className="font-serif text-3xl lg:text-4xl text-white mt-1" data-testid="dashboard-greeting">
              Hello, {user?.full_name?.split(' ')[0] || 'Roshini'}
            </h1>
            <p className="text-white/70 mt-1 text-sm">Here's your sales intelligence overview — crafting memorable spaces since 1995</p>
          </div>
        </div>
      </motion.div>

      {/* Filters */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
        className="flex flex-wrap items-center gap-3"
      >
          {/* Time Filter */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                className="bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 hover:text-[#C5A059]"
                data-testid="time-filter-dropdown"
              >
                <Calendar size={16} className="mr-2" />
                {timeFilters.find(f => f.value === timeFilter)?.label || 'All Time'}
                <ChevronDown size={16} className="ml-2" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="bg-[#1A1A1A] border-white/10">
              {timeFilters.map((filter) => (
                <DropdownMenuItem
                  key={filter.value}
                  onClick={() => setTimeFilter(filter.value)}
                  className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                  data-testid={`time-filter-${filter.value}`}
                >
                  {filter.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Project Filter */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                className="bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 hover:text-[#C5A059]"
                data-testid="project-filter-dropdown"
              >
                {projectFilter === 'all' ? 'All Projects' : projectFilter}
                <ChevronDown size={16} className="ml-2" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="bg-[#1A1A1A] border-white/10">
              <DropdownMenuItem
                onClick={() => setProjectFilter('all')}
                className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
              >
                All Projects
              </DropdownMenuItem>
              {projects.map((project) => (
                <DropdownMenuItem
                  key={project}
                  onClick={() => setProjectFilter(project)}
                  className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                >
                  {project}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Custom Date Range */}
          {timeFilter === 'custom' && (
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  className="bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5"
                >
                  Select Date Range
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-auto p-0 bg-[#1A1A1A] border-white/10">
                <CalendarUI
                  mode="range"
                  selected={dateRange}
                  onSelect={setDateRange}
                  className="bg-[#1A1A1A] text-white"
                />
              </PopoverContent>
            </Popover>
          )}
      </motion.div>

      {/* Cold & Dormant Alert Tiles with Info Tooltips */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="grid grid-cols-1 md:grid-cols-2 gap-4"
      >
        <div className="glass-card rounded-lg p-6 border-l-4 border-blue-500 card-hover" data-testid="cold-leads-tile">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center">
                <p className="text-[#A1A1AA] text-sm uppercase tracking-wider">Cold Leads</p>
                <LeadCriteriaTooltip type="cold" />
              </div>
              <p className="font-serif text-4xl text-white mt-2">{analytics?.cold_leads || 0}</p>
              <p className="text-blue-400 text-sm mt-1">Needs Re-engagement</p>
            </div>
            <div className="w-14 h-14 rounded-full bg-blue-500/20 flex items-center justify-center">
              <Snowflake className="text-blue-500" size={28} />
            </div>
          </div>
        </div>

        <div className="glass-card rounded-lg p-6 border-l-4 border-orange-500 card-hover" data-testid="dormant-leads-tile">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center">
                <p className="text-[#A1A1AA] text-sm uppercase tracking-wider">Dormant Leads</p>
                <LeadCriteriaTooltip type="dormant" />
              </div>
              <p className="font-serif text-4xl text-white mt-2">
                {analytics?.dormant_leads ?? 0}
              </p>
              <p className="text-orange-400 text-sm mt-1">No activity in 7+ days</p>
            </div>
            <div className="w-14 h-14 rounded-full bg-orange-500/20 flex items-center justify-center">
              <TrendingDown className="text-orange-500" size={28} />
            </div>
          </div>
        </div>
      </motion.div>

      {/* Key Metrics Grid with Info Tooltips */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
      >
        {/* Total Leads */}
        <div className="glass-card rounded-lg p-6 card-hover" data-testid="total-leads-tile">
          <div className="flex items-center justify-between mb-4">
            <div className="w-12 h-12 rounded-lg bg-[#C5A059]/20 flex items-center justify-center">
              <Users className="text-[#C5A059]" size={24} />
            </div>
            <span className="flex items-center gap-1 text-green-500 text-sm">
              <TrendingUp size={14} /> +12%
            </span>
          </div>
          <p className="text-[#A1A1AA] text-sm">Total Leads</p>
          <p className="font-serif text-3xl text-white mt-1">{analytics?.total_leads || 0}</p>
        </div>

        {/* VIP Pipeline */}
        <div className="glass-card rounded-lg p-6 card-hover" data-testid="vip-leads-tile">
          <div className="flex items-center justify-between mb-4">
            <div className="w-12 h-12 rounded-lg bg-purple-500/20 flex items-center justify-center">
              <Crown className="text-purple-500" size={24} />
            </div>
            <span className="flex items-center gap-1 text-green-500 text-sm">
              <TrendingUp size={14} /> +8%
            </span>
          </div>
          <div className="flex items-center gap-1">
            <p className="text-[#A1A1AA] text-sm">VIP Pipeline</p>
            <LeadCriteriaTooltip type="vip" />
          </div>
          <p className="font-serif text-3xl text-white mt-1">{analytics?.vip_leads || 0}</p>
        </div>

        {/* Hot Leads */}
        <div className="glass-card rounded-lg p-6 card-hover" data-testid="hot-leads-tile">
          <div className="flex items-center justify-between mb-4">
            <div className="w-12 h-12 rounded-lg bg-red-500/20 flex items-center justify-center">
              <Flame className="text-red-500" size={24} />
            </div>
            <LeadCriteriaTooltip type="hot" />
          </div>
          <p className="text-[#A1A1AA] text-sm">Hot Leads</p>
          <p className="font-serif text-3xl text-white mt-1">{analytics?.hot_leads || 0}</p>
        </div>

        {/* Qualified Leads */}
        <div className="glass-card rounded-lg p-6 card-hover" data-testid="qualified-leads-tile">
          <div className="flex items-center justify-between mb-4">
            <div className="w-12 h-12 rounded-lg bg-green-500/20 flex items-center justify-center">
              <CheckCircle className="text-green-500" size={24} />
            </div>
            <span className="flex items-center gap-1 text-green-500 text-sm">
              <TrendingUp size={14} /> +5%
            </span>
          </div>
          <div className="flex items-center gap-1">
            <p className="text-[#A1A1AA] text-sm">Qualified Leads</p>
            <LeadCriteriaTooltip type="qualified" />
          </div>
          <p className="font-serif text-3xl text-white mt-1">{analytics?.qualified_leads || 0}</p>
        </div>
      </motion.div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Lead Source Performance */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.3 }}
          className="glass-card rounded-lg p-6"
          data-testid="lead-source-chart"
        >
          <h3 className="font-serif text-xl text-white mb-6">Lead Source Performance</h3>
          <ResponsiveContainer width="100%" height={400}>
            <BarChart
              data={analytics?.lead_sources || []}
              layout="vertical"
              margin={{ top: 0, right: 20, bottom: 0, left: 10 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis type="number" stroke="#52525B" />
              <YAxis type="category" dataKey="name" stroke="#A1A1AA" tick={{ fill: '#A1A1AA', fontSize: 11 }} width={140} />
              <Tooltip content={<CustomTooltip />} />
              <Bar
                dataKey="count"
                fill="url(#goldGradient)"
                radius={[0, 4, 4, 0]}
              />
              <defs>
                <linearGradient id="goldGradient" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#C5A059" />
                  <stop offset="100%" stopColor="#E5C079" />
                </linearGradient>
              </defs>
            </BarChart>
          </ResponsiveContainer>
        </motion.div>

        {/* Lead Status Distribution */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.3 }}
          className="glass-card rounded-lg p-6"
          data-testid="lead-status-chart"
        >
          <h3 className="font-serif text-xl text-white mb-6">Lead Status Distribution</h3>
          <div className="flex items-center justify-center">
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={statusData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {statusData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      return (
                        <div className="bg-[#1A1A1A] border border-white/10 rounded-lg p-3 shadow-xl">
                          <p className="text-[#C5A059] font-medium">{payload[0].name}</p>
                          <p className="text-white">{payload[0].value} leads</p>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          {/* Legend */}
          <div className="flex flex-wrap justify-center gap-x-4 gap-y-2 mt-4">
            {statusData.map((item) => (
              <div key={item.name} className="flex items-center gap-2">
                <div
                  className="w-3 h-3 rounded-full flex-shrink-0"
                  style={{ backgroundColor: item.color }}
                />
                <span className="text-[#A1A1AA] text-xs whitespace-nowrap">{item.name} ({item.value})</span>
              </div>
            ))}
          </div>
        </motion.div>
      </div>

      {/* Sales Team Performance — admins only */}
      {user?.role === 'admin' && (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="glass-card rounded-lg p-6"
        data-testid="sales-team-heatmap"
      >
        <h3 className="font-serif text-xl text-white mb-6">Sales Team Performance</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          {(analytics?.sales_owners || []).map((owner, index) => {
            const colorScheme = REGIONAL_COLORS[index % REGIONAL_COLORS.length];
            return (
              <div
                key={owner.name}
                className="p-4 rounded-lg text-center transition-all hover:scale-105 cursor-pointer"
                onClick={() => navigate(`/sales-dashboard?agent=${encodeURIComponent(owner.name)}`)}
                style={{
                  background: colorScheme.bg,
                  border: `2px solid ${colorScheme.border}`
                }}
              >
                <p className="text-white font-medium text-sm">{owner.name}</p>
                <p className="font-serif text-2xl mt-1" style={{ color: colorScheme.text }}>{owner.count}</p>
                <p className="text-[#52525B] text-xs">leads</p>
              </div>
            );
          })}
        </div>
      </motion.div>
      )}

      {/* Project Distribution - Clickable to filter Virtual Customers */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
        className="glass-card rounded-lg p-6"
        data-testid="project-distribution"
      >
        <h3 className="font-serif text-xl text-white mb-6">Project Interest Distribution</h3>
        <p className="text-[#52525B] text-sm mb-4">Click on a project to view its leads</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {topProjects.map((project) => (
            <div
              key={project.name}
              onClick={() => handleProjectClick(project.name)}
              className="p-4 rounded-lg bg-[#1A1A1A] border border-white/10 hover:border-[#C5A059]/50 transition-all cursor-pointer group overflow-hidden relative"
              data-testid={`project-card-${project.name}`}
            >
              {PROJECT_IMAGES[project.name] && (
                <div
                  className="absolute inset-0 opacity-20 group-hover:opacity-30 transition-opacity bg-cover bg-center"
                  style={{ backgroundImage: `url(${PROJECT_IMAGES[project.name]})` }}
                />
              )}
              <div className="relative z-10">
                <div className="flex items-center gap-2 mb-3">
                  <Building className="text-[#C5A059]" size={18} />
                  <span className="text-white font-medium group-hover:text-[#C5A059] transition-colors">{project.name}</span>
                </div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[#52525B] text-sm">Leads</span>
                  <span className="text-[#C5A059] font-serif text-xl">{project.count}</span>
                </div>
                <div className="h-2 bg-black/50 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-[#C5A059] to-[#E5C079] rounded-full transition-all duration-500"
                    style={{ width: `${(project.count / maxProjectCount) * 100}%` }}
                  />
                </div>
                <p className="text-[#52525B] text-xs mt-2 group-hover:text-[#A1A1AA] transition-colors">
                  Click to view leads →
                </p>
              </div>
            </div>
          ))}
          {otherProjects.length > 0 && (
            <div
              onClick={() => setOtherModalOpen(true)}
              className="p-4 rounded-lg bg-[#1A1A1A] border border-white/10 hover:border-[#C5A059]/50 transition-all cursor-pointer group overflow-hidden relative"
              data-testid="project-card-Other"
            >
              <div className="relative z-10">
                <div className="flex items-center gap-2 mb-3">
                  <Layers className="text-[#C5A059]" size={18} />
                  <span className="text-white font-medium group-hover:text-[#C5A059] transition-colors">Other</span>
                </div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[#52525B] text-sm">Leads</span>
                  <span className="text-[#C5A059] font-serif text-xl">{otherTotal}</span>
                </div>
                <div className="h-2 bg-black/50 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-[#C5A059] to-[#E5C079] rounded-full transition-all duration-500"
                    style={{ width: `${(otherTotal / maxProjectCount) * 100}%` }}
                  />
                </div>
                <p className="text-[#52525B] text-xs mt-2 group-hover:text-[#A1A1AA] transition-colors">
                  Click to view all projects →
                </p>
              </div>
            </div>
          )}
        </div>
      </motion.div>

      <Dialog open={otherModalOpen} onOpenChange={setOtherModalOpen}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl text-[#EDEDED]">Other projects</DialogTitle>
            <DialogDescription className="text-[#A1A1AA]">
              {otherProjects.length} project{otherProjects.length !== 1 ? 's' : ''} · {otherTotal} leads total
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto space-y-2 pr-1">
            {otherProjects.map((project) => (
              <button
                key={project.name}
                type="button"
                onClick={() => handleOtherProjectClick(project.name)}
                className="w-full flex items-center justify-between gap-4 p-3 rounded-lg bg-black/30 border border-white/10 hover:border-[#C5A059]/50 hover:bg-white/5 transition-all text-left cursor-pointer group"
                data-testid={`other-project-row-${project.name}`}
              >
                <span className="text-white font-medium group-hover:text-[#C5A059] transition-colors truncate">
                  {project.name}
                </span>
                <span className="text-[#C5A059] font-serif text-lg flex-shrink-0">{project.count}</span>
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default DashboardPage;
