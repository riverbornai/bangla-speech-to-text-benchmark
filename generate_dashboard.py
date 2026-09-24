#!/usr/bin/env python3
"""
Generates an interactive, beautiful HTML dashboard for visualizing Bangla ASR benchmark results.
Reads: results/leaderboard.csv, results/by_domain.csv, results/per_file.csv
Writes: results/dashboard.html
"""
import os
import csv
import json
import sys

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(base_dir, "results")
    
    leaderboard_path = os.path.join(results_dir, "leaderboard.csv")
    by_domain_path = os.path.join(results_dir, "by_domain.csv")
    per_file_path = os.path.join(results_dir, "per_file.csv")
    output_path = os.path.join(results_dir, "dashboard.html")
    
    # Verify inputs
    missing_files = []
    for path, name in [(leaderboard_path, "leaderboard.csv"), 
                       (by_domain_path, "by_domain.csv"), 
                       (per_file_path, "per_file.csv")]:
        if not os.path.exists(path):
            missing_files.append(name)
            
    if missing_files:
        print(f"Error: The following result files are missing in results/: {', '.join(missing_files)}", file=sys.stderr)
        print("Please run evaluations first to generate these files.", file=sys.stderr)
        sys.exit(1)
        
    print("Parsing CSV results...")
    
    # 1. Parse Leaderboard
    leaderboard = []
    with open(leaderboard_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leaderboard.append({
                "model": row["model"],
                "files_scored": int(row["files_scored"]),
                "coverage": float(row["coverage"]),
                "cer": float(row["CER"]),
                "wer": float(row["WER"]),
                "mean_latency_s": float(row["mean_latency_s"])
            })
            
    # 2. Parse By Domain
    by_domain = []
    with open(by_domain_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            model = row["model"]
            domain_data = {}
            for k, v in row.items():
                if k != "model":
                    try:
                        domain_data[k] = float(v)
                    except ValueError:
                        domain_data[k] = v
            by_domain.append({
                "model": model,
                "domains": domain_data
            })
            
    # 3. Parse Per File (might be around 800 rows)
    per_file = []
    with open(per_file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            per_file.append({
                "model": row["model"],
                "file_path": row["file_path"],
                "domain": row["domain"],
                "cer": float(row["cer"]),
                "wer": float(row["wer"]),
                "ref": row["ref"],
                "hyp": row["hyp"]
            })
            
    print(f"Loaded {len(leaderboard)} models, CER breakdown for {len(by_domain[0]['domains']) if by_domain else 0} domains, and {len(per_file)} per-file transcript records.")

    # Calculate global stats
    best_model_cer = min(leaderboard, key=lambda x: x["cer"])
    best_model_latency = min(leaderboard, key=lambda x: x["mean_latency_s"])
    avg_cer = sum(x["cer"] for x in leaderboard) / len(leaderboard)
    avg_latency = sum(x["mean_latency_s"] for x in leaderboard) / len(leaderboard)

    global_stats = {
        "best_model_cer_name": best_model_cer["model"],
        "best_model_cer_val": best_model_cer["cer"],
        "best_model_latency_name": best_model_latency["model"],
        "best_model_latency_val": best_model_latency["mean_latency_s"],
        "avg_cer": avg_cer,
        "avg_latency": avg_latency,
        "total_models": len(leaderboard),
        "total_files": max([x["files_scored"] for x in leaderboard]) if leaderboard else 100
    }

    # Generate HTML content
    html_template = r"""<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bangla ASR Benchmark Dashboard</title>
  <!-- Outfit Font & JetBrains Mono -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  
  <!-- Tailwind CSS CDN -->
  <script src="https://cdn.tailwindcss.com"></script>
  
  <!-- Chart.js CDN -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

  <script>
    tailwind.config = {
      theme: {
        extend: {
          fontFamily: {
            sans: ['Outfit', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace'],
          }
        }
      }
    }
  </script>

  <style>
    /* Custom scrollbars */
    ::-webkit-scrollbar {
      width: 6px;
      height: 6px;
    }
    ::-webkit-scrollbar-track {
      background: rgba(15, 23, 42, 0.3);
    }
    ::-webkit-scrollbar-thumb {
      background: rgba(148, 163, 184, 0.3);
      border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
      background: rgba(148, 163, 184, 0.5);
    }
    .gradient-bg {
      background: radial-gradient(circle at top right, rgba(99, 102, 241, 0.15), transparent 45%),
                  radial-gradient(circle at bottom left, rgba(168, 85, 247, 0.1), transparent 50%),
                  #020617;
    }
    .glass-card {
      background: rgba(15, 23, 42, 0.65);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .glass-card-hover {
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .glass-card-hover:hover {
      transform: translateY(-2px);
      border-color: rgba(99, 102, 241, 0.25);
      box-shadow: 0 10px 30px -10px rgba(99, 102, 241, 0.2);
    }
  </style>
</head>
<body class="gradient-bg text-slate-100 min-h-full font-sans antialiased pb-12">

  <!-- Header -->
  <header class="border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-md sticky top-0 z-30">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      <div>
        <div class="flex items-center gap-3">
          <span class="px-2.5 py-1 text-xs font-semibold tracking-wider text-indigo-400 bg-indigo-500/10 rounded-full border border-indigo-500/20 uppercase">Benchmark Report</span>
          <span class="text-xs text-slate-400">100 Utterances • 13 Domains (BanSpeech)</span>
        </div>
        <h1 class="text-2xl font-extrabold tracking-tight mt-1 bg-gradient-to-r from-white via-slate-100 to-indigo-200 bg-clip-text text-transparent">
          Bangla ASR Performance Dashboard
        </h1>
      </div>
      
      <!-- Tabs Navigation -->
      <nav class="flex space-x-1 bg-slate-900/80 p-1 rounded-xl border border-slate-800" aria-label="Tabs">
        <button id="tab-leaderboard-btn" onclick="switchTab('leaderboard')" class="px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 bg-indigo-600 text-white shadow">
          Leaderboard & Charts
        </button>
        <button id="tab-heatmap-btn" onclick="switchTab('heatmap')" class="px-4 py-2 text-sm font-medium rounded-lg text-slate-400 hover:text-slate-200 transition-all duration-200">
          Domain Matrix
        </button>
        <button id="tab-explorer-btn" onclick="switchTab('explorer')" class="px-4 py-2 text-sm font-medium rounded-lg text-slate-400 hover:text-slate-200 transition-all duration-200">
          Transcript Explorer
        </button>
      </nav>
    </div>
  </header>

  <!-- Main Container -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-8">

    <!-- KPI Summary Grid -->
    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-8">
      
      <!-- Top Performer CER -->
      <div class="glass-card glass-card-hover rounded-2xl p-6 relative overflow-hidden">
        <div class="absolute right-4 top-4 text-emerald-400 bg-emerald-500/10 p-2 rounded-xl border border-emerald-500/20">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
          </svg>
        </div>
        <p class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Top CER Accuracy</p>
        <h3 class="text-2xl font-bold text-white mt-2" id="kpi-best-cer-val">0.00%</h3>
        <p class="text-sm font-medium text-emerald-400 mt-1 flex items-center gap-1">
          <span class="truncate" id="kpi-best-cer-name">-</span>
        </p>
      </div>

      <!-- Speed Champion -->
      <div class="glass-card glass-card-hover rounded-2xl p-6 relative overflow-hidden">
        <div class="absolute right-4 top-4 text-amber-400 bg-amber-500/10 p-2 rounded-xl border border-amber-500/20">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/>
          </svg>
        </div>
        <p class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Fastest Latency</p>
        <h3 class="text-2xl font-bold text-white mt-2" id="kpi-best-lat-val">0.00s</h3>
        <p class="text-sm font-medium text-amber-400 mt-1 flex items-center gap-1">
          <span class="truncate" id="kpi-best-lat-name">-</span>
        </p>
      </div>

      <!-- Average CER -->
      <div class="glass-card glass-card-hover rounded-2xl p-6 relative overflow-hidden">
        <div class="absolute right-4 top-4 text-indigo-400 bg-indigo-500/10 p-2 rounded-xl border border-indigo-500/20">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h2a2 2 0 002-2z"/>
          </svg>
        </div>
        <p class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Average Benchmark CER</p>
        <h3 class="text-2xl font-bold text-white mt-2" id="kpi-avg-cer">0.00%</h3>
        <p class="text-sm text-slate-400 mt-1">Across all models</p>
      </div>

      <!-- Dataset Size -->
      <div class="glass-card glass-card-hover rounded-2xl p-6 relative overflow-hidden">
        <div class="absolute right-4 top-4 text-purple-400 bg-purple-500/10 p-2 rounded-xl border border-purple-500/20">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
          </svg>
        </div>
        <p class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Evaluated dataset</p>
        <h3 class="text-2xl font-bold text-white mt-2" id="kpi-total-files">100 files</h3>
        <p class="text-sm text-indigo-300 mt-1" id="kpi-total-models">8 ASR Models</p>
      </div>

    </section>

    <!-- Tab 1: Leaderboard & Charts -->
    <section id="tab-leaderboard" class="space-y-8">
      
      <!-- Grid: Table & Radar Chart -->
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        <!-- Leaderboard Table (8 cols) -->
        <div class="lg:col-span-7 glass-card rounded-2xl p-6 flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between mb-4">
              <div>
                <h2 class="text-lg font-bold text-white">Model Leaderboard</h2>
                <p class="text-xs text-slate-400">Aggregated evaluations. Sort by clicking column headers.</p>
              </div>
              <span class="text-xs text-indigo-400 font-mono">Lower is better</span>
            </div>
            
            <div class="overflow-x-auto">
              <table class="w-full text-left text-sm" id="leaderboard-table">
                <thead>
                  <tr class="border-b border-slate-800 text-slate-400 font-semibold select-none">
                    <th onclick="sortLeaderboard('model')" class="pb-3 cursor-pointer hover:text-white transition py-2 pr-4">Model</th>
                    <th onclick="sortLeaderboard('cer')" class="pb-3 cursor-pointer hover:text-white transition py-2 text-right">CER</th>
                    <th onclick="sortLeaderboard('wer')" class="pb-3 cursor-pointer hover:text-white transition py-2 text-right">WER</th>
                    <th onclick="sortLeaderboard('mean_latency_s')" class="pb-3 cursor-pointer hover:text-white transition py-2 text-right">Latency</th>
                    <th onclick="sortLeaderboard('coverage')" class="pb-3 cursor-pointer hover:text-white transition py-2 text-right hidden sm:table-cell">Coverage</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-800/60" id="leaderboard-body">
                  <!-- JS generated rows -->
                </tbody>
              </table>
            </div>
          </div>
          <div class="mt-6 pt-4 border-t border-slate-800 text-xs text-slate-400 leading-relaxed">
            <strong>Metrics explanation:</strong><br/>
            • <strong>CER (Character Error Rate)</strong>: Primary metric. Percentage of character changes needed to align hypothesis with reference.<br/>
            • <strong>WER (Word Error Rate)</strong>: Word alignment error percentage.<br/>
            • <strong>Latency</strong>: Mean inference time in seconds per utterance.
          </div>
        </div>

        <!-- Radar or Comparison Chart (5 cols) -->
        <div class="lg:col-span-5 glass-card rounded-2xl p-6 flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between mb-4">
              <div>
                <h2 class="text-lg font-bold text-white" id="chart-title">Model Performance Radar</h2>
                <p class="text-xs text-slate-400">CER breakdown across domains (smaller area is better).</p>
              </div>
              <select id="chart-type-select" onchange="updateChartType()" class="bg-slate-900 border border-slate-800 text-slate-300 rounded-lg text-xs px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500">
                <option value="radar">Radar Chart</option>
                <option value="bar">Bar Chart</option>
              </select>
            </div>
            
            <div class="relative w-full h-[320px] flex items-center justify-center">
              <canvas id="domain-chart"></canvas>
            </div>
          </div>

          <!-- Model filter checkboxes for Chart -->
          <div class="mt-6 pt-4 border-t border-slate-800">
            <p class="text-xs font-semibold text-slate-400 mb-2">Display Models:</p>
            <div class="grid grid-cols-2 sm:grid-cols-3 gap-2" id="model-checkboxes">
              <!-- Checkboxes injected by JS -->
            </div>
          </div>
        </div>

      </div>

    </section>

    <!-- Tab 2: Domain Matrix -->
    <section id="tab-heatmap" class="hidden space-y-6">
      <div class="glass-card rounded-2xl p-6 overflow-hidden">
        <div>
          <h2 class="text-lg font-bold text-white">Domain CER Comparison Grid</h2>
          <p class="text-xs text-slate-400 mb-6">Each cell shows the Character Error Rate (CER) for the model in that domain. Color intensity indicates error rate (green is better, red is higher error).</p>
        </div>

        <div class="overflow-x-auto w-full max-w-full">
          <table class="w-full text-left text-sm border-collapse" id="heatmap-table">
            <thead>
              <tr class="border-b border-slate-800 text-slate-400 font-semibold whitespace-nowrap">
                <th class="p-3 bg-slate-950/60 sticky left-0 z-10">Model</th>
                <!-- Domain headers added by JS -->
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60" id="heatmap-body">
              <!-- Rows added by JS -->
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- Tab 3: Transcript Explorer -->
    <section id="tab-explorer" class="hidden space-y-6">
      
      <!-- Filters Card -->
      <div class="glass-card rounded-2xl p-6">
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
          <div>
            <h2 class="text-lg font-bold text-white">Utterance Transcript Inspector</h2>
            <p class="text-xs text-slate-400">Search and filter through the 800+ transcript evaluations. Inspect errors word-by-word.</p>
          </div>
          
          <!-- Quick Export summary -->
          <div class="text-xs text-slate-400" id="explorer-counter">
            Showing 0 of 0 records
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <!-- Model Filter -->
          <div>
            <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Model</label>
            <select id="filter-model" onchange="applyFilters()" class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl p-3 text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500">
              <option value="all">All Models</option>
              <!-- Options filled by JS -->
            </select>
          </div>

          <!-- Domain Filter -->
          <div>
            <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Domain</label>
            <select id="filter-domain" onchange="applyFilters()" class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl p-3 text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500">
              <option value="all">All Domains</option>
              <!-- Options filled by JS -->
            </select>
          </div>

          <!-- Error Filter -->
          <div>
            <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">CER Threshold</label>
            <select id="filter-cer" onchange="applyFilters()" class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl p-3 text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500">
              <option value="all">All Errors</option>
              <option value="perfect">Perfect (CER = 0.00)</option>
              <option value="errors">Any Errors (CER > 0.00)</option>
              <option value="low">Low (0.00 < CER &le; 0.10)</option>
              <option value="mid">Medium (0.10 < CER &le; 0.30)</option>
              <option value="high">High (CER > 0.30)</option>
            </select>
          </div>

          <!-- Search Query -->
          <div>
            <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Search Text / File</label>
            <div class="relative">
              <input type="text" id="filter-search" oninput="applyFilters()" placeholder="Search transcripts or files..." class="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-xl py-3 pl-10 pr-4 text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500">
              <div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                </svg>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Table Card -->
      <div class="glass-card rounded-2xl overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm">
            <thead>
              <tr class="border-b border-slate-800 bg-slate-900/40 text-slate-400 font-semibold">
                <th class="p-4">Model</th>
                <th class="p-4">Domain</th>
                <th class="p-4 hidden md:table-cell">File Name</th>
                <th class="p-4 text-center cursor-pointer hover:text-white" onclick="toggleSortExplorer('cer')">CER</th>
                <th class="p-4 text-center cursor-pointer hover:text-white" onclick="toggleSortExplorer('wer')">WER</th>
                <th class="p-4">Transcripts (Ref vs Hyp)</th>
                <th class="p-4 text-center">Action</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/50" id="explorer-body">
              <!-- JS injected rows -->
            </tbody>
          </table>
        </div>

        <!-- Empty state -->
        <div id="explorer-empty" class="hidden py-16 text-center">
          <svg class="w-12 h-12 mx-auto text-slate-600 mb-3" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <h3 class="text-sm font-semibold text-slate-300">No matching utterances found</h3>
          <p class="text-xs text-slate-500 mt-1">Try adjusting your search queries or drop-down filters.</p>
        </div>

        <!-- Pagination Footer -->
        <div class="bg-slate-900/20 border-t border-slate-800/80 px-4 py-3.5 flex items-center justify-between sm:px-6">
          <div class="flex-1 flex justify-between sm:hidden">
            <button onclick="prevPage()" class="relative inline-flex items-center px-4 py-2 border border-slate-800 text-sm font-medium rounded-xl text-slate-300 bg-slate-900 hover:bg-slate-800 transition">
              Previous
            </button>
            <button onclick="nextPage()" class="ml-3 relative inline-flex items-center px-4 py-2 border border-slate-800 text-sm font-medium rounded-xl text-slate-300 bg-slate-900 hover:bg-slate-800 transition">
              Next
            </button>
          </div>
          <div class="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
            <div>
              <p class="text-xs text-slate-400">
                Showing <span class="font-medium text-slate-200" id="page-start">1</span> to <span class="font-medium text-slate-200" id="page-end">10</span> of <span class="font-medium text-slate-200" id="page-total">100</span> entries
              </p>
            </div>
            <div>
              <nav class="relative z-0 inline-flex rounded-xl shadow-sm -space-x-px border border-slate-800 p-0.5 bg-slate-950/40" aria-label="Pagination">
                <button onclick="prevPage()" class="relative inline-flex items-center px-2 py-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-900 transition">
                  <span class="sr-only">Previous</span>
                  <svg class="h-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
                </button>
                <div id="pagination-pages" class="flex space-x-1 px-2">
                  <!-- Page numbers injected by JS -->
                </div>
                <button onclick="nextPage()" class="relative inline-flex items-center px-2 py-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-900 transition">
                  <span class="sr-only">Next</span>
                  <svg class="h-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                </button>
              </nav>
            </div>
          </div>
        </div>

      </div>
    </section>

  </main>

  <!-- Detailed Modal -->
  <div id="details-modal" class="fixed inset-0 z-50 overflow-y-auto hidden" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
      
      <!-- Backdrop -->
      <div onclick="closeModal()" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm transition-opacity" aria-hidden="true"></div>

      <!-- Centered Modal Content -->
      <span class="hidden sm:inline-block sm:align-middle sm:h-screen" aria-hidden="true">&#8203;</span>
      
      <div class="inline-block align-bottom bg-slate-900 border border-slate-850 rounded-2xl text-left overflow-hidden shadow-2xl transform transition-all sm:my-8 sm:align-middle sm:max-w-3xl sm:w-full">
        <!-- Close Button top right -->
        <button onclick="closeModal()" class="absolute top-4 right-4 text-slate-400 hover:text-slate-200 focus:outline-none">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>

        <!-- Header -->
        <div class="p-6 pb-4 border-b border-slate-800 bg-slate-950/40">
          <div class="flex flex-wrap items-center gap-2 mb-2">
            <span id="modal-model-badge" class="px-2.5 py-0.5 text-xs font-semibold text-indigo-400 bg-indigo-500/10 rounded-full border border-indigo-500/20"></span>
            <span id="modal-domain-badge" class="px-2.5 py-0.5 text-xs font-semibold text-slate-400 bg-slate-800 rounded-full border border-slate-700"></span>
          </div>
          <h3 class="text-lg font-bold text-white leading-6 truncate" id="modal-title-file">File Name</h3>
          <p class="text-xs text-slate-500 mt-1 font-mono break-all" id="modal-path"></p>
        </div>

        <!-- Body -->
        <div class="p-6 space-y-6">
          
          <!-- Metics comparison -->
          <div class="grid grid-cols-2 gap-4">
            <div class="bg-slate-950/30 p-4 rounded-xl border border-slate-800 text-center">
              <span class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Character Error Rate</span>
              <span class="text-3xl font-extrabold text-white" id="modal-cer">-</span>
            </div>
            <div class="bg-slate-950/30 p-4 rounded-xl border border-slate-800 text-center">
              <span class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Word Error Rate</span>
              <span class="text-3xl font-extrabold text-white" id="modal-wer">-</span>
            </div>
          </div>

          <!-- Local Audio Player (Falls back if not downloaded) -->
          <div class="space-y-2">
            <div class="flex justify-between items-center">
              <span class="block text-xs font-semibold text-slate-400 uppercase tracking-wider">Audio Playback</span>
              <span class="text-[10px] text-slate-500">Requires download_benchmark_audio.py to have been run</span>
            </div>
            <div class="bg-slate-950/40 p-4 rounded-xl border border-slate-800 flex items-center gap-4">
              <audio id="modal-audio-player" class="w-full focus:outline-none" controls></audio>
            </div>
          </div>

          <!-- Transcripts & Diff -->
          <div class="space-y-4">
            
            <!-- Reference -->
            <div class="space-y-1.5">
              <span class="block text-xs font-semibold text-slate-400 uppercase tracking-wider">Reference (Ground Truth)</span>
              <div class="bg-slate-950/50 p-4 rounded-xl border border-slate-850 text-slate-200 leading-relaxed text-base font-medium select-all" id="modal-ref">
                -
              </div>
            </div>

            <!-- Hypothesis -->
            <div class="space-y-1.5">
              <span class="block text-xs font-semibold text-slate-400 uppercase tracking-wider">Hypothesis (ASR Output)</span>
              <div class="bg-slate-950/50 p-4 rounded-xl border border-slate-850 text-slate-200 leading-relaxed text-base font-medium select-all" id="modal-hyp">
                -
              </div>
            </div>

            <!-- Alignment Word Diff -->
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="block text-xs font-semibold text-slate-400 uppercase tracking-wider">Alignment Word-level Diff</span>
                <div class="flex items-center gap-3 text-[10px] text-slate-400">
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded bg-red-500/20 border border-red-500/30"></span>Deleted/Error</span>
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded bg-emerald-500/20 border border-emerald-500/30"></span>Inserted/Extra</span>
                </div>
              </div>
              <div class="bg-slate-950 border border-slate-850 p-4 rounded-xl leading-relaxed text-base" id="modal-diff">
                <!-- Diff rendered here -->
              </div>
            </div>

          </div>

        </div>

        <!-- Footer -->
        <div class="px-6 py-4 bg-slate-950/60 border-t border-slate-800 flex justify-end">
          <button onclick="closeModal()" type="button" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-sm font-semibold transition">
            Close Panel
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Embedded Datasets and JS logic -->
  <script>
    // Data populated by generate_dashboard.py
    const globalStats = %GLOBAL_STATS_JSON%;
    const leaderboardData = %LEADERBOARD_JSON%;
    const byDomainData = %BY_DOMAIN_JSON%;
    const perFileData = %PER_FILE_JSON%;

    // Active state
    let activeTab = 'leaderboard';
    let leaderboardSortCol = 'cer';
    let leaderboardSortAsc = true;
    let selectedModelsForChart = [];
    let domainChartInstance = null;
    let chartType = 'radar';

    // Explorer variables
    let filteredRecords = [];
    let currentPage = 1;
    let itemsPerPage = 10;
    let explorerSortCol = 'cer';
    let explorerSortAsc = false; // default worst errors first for debugging

    // Format utility
    function pct(val) {
      return (val * 100).toFixed(2) + '%';
    }

    function capitalize(str) {
      return str.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }

    // Initialize stats
    document.getElementById('kpi-best-cer-val').innerText = pct(globalStats.best_model_cer_val);
    document.getElementById('kpi-best-cer-name').innerText = capitalize(globalStats.best_model_cer_name);
    document.getElementById('kpi-best-lat-val').innerText = globalStats.best_model_latency_val.toFixed(2) + 's';
    document.getElementById('kpi-best-lat-name').innerText = capitalize(globalStats.best_model_latency_name);
    document.getElementById('kpi-avg-cer').innerText = pct(globalStats.avg_cer);
    document.getElementById('kpi-total-files').innerText = globalStats.total_files + ' files';
    document.getElementById('kpi-total-models').innerText = globalStats.total_models + ' ASR Models';

    // Switch tabs
    function switchTab(tabId) {
      activeTab = tabId;
      
      // Update UI classes
      const tabs = ['leaderboard', 'heatmap', 'explorer'];
      tabs.forEach(t => {
        const btn = document.getElementById(`tab-${t}-btn`);
        const section = document.getElementById(`tab-${t}`);
        if (t === tabId) {
          btn.className = "px-4 py-2 text-sm font-medium rounded-lg bg-indigo-600 text-white shadow";
          section.classList.remove('hidden');
        } else {
          btn.className = "px-4 py-2 text-sm font-medium rounded-lg text-slate-400 hover:text-slate-200 transition-all duration-200";
          section.classList.add('hidden');
        }
      });

      // Special re-render triggers
      if (tabId === 'leaderboard' && domainChartInstance) {
        domainChartInstance.resize();
      }
    }

    // 1. Leaderboard Table logic
    function renderLeaderboard() {
      // Sort data
      leaderboardData.sort((a, b) => {
        let valA = a[leaderboardSortCol];
        let valB = b[leaderboardSortCol];
        if (typeof valA === 'string') {
          return leaderboardSortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }
        return leaderboardSortAsc ? valA - valB : valB - valA;
      });

      const tbody = document.getElementById('leaderboard-body');
      tbody.innerHTML = '';

      leaderboardData.forEach((row, idx) => {
        const tr = document.createElement('tr');
        tr.className = "hover:bg-slate-900/30 transition-colors border-b border-slate-800/40 group";
        
        // CER color coding (red -> orange -> green)
        let cerColor = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
        if (row.cer > 0.25) cerColor = 'text-red-400 bg-red-500/10 border-red-500/20';
        else if (row.cer > 0.12) cerColor = 'text-amber-400 bg-amber-500/10 border-amber-500/20';

        // WER color coding
        let werColor = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
        if (row.wer > 0.45) werColor = 'text-red-400 bg-red-500/10 border-red-500/20';
        else if (row.wer > 0.25) werColor = 'text-amber-400 bg-amber-500/10 border-amber-500/20';

        // Visual CER Bar percentage width
        const cerPct = Math.min(row.cer * 100, 100);

        tr.innerHTML = `
          <td class="py-4 pr-4 font-semibold text-white">
            <span class="text-slate-500 font-mono mr-2">${idx + 1}</span>
            <span class="hover:text-indigo-400 transition cursor-pointer" onclick="openModelExplorer('${row.model}')">${capitalize(row.model)}</span>
          </td>
          <td class="py-4 text-right font-mono font-semibold">
            <div class="flex items-center justify-end gap-2.5">
              <span class="px-2 py-0.5 text-xs rounded-lg border ${cerColor}">${pct(row.cer)}</span>
              <div class="w-16 bg-slate-800 h-1.5 rounded-full overflow-hidden hidden sm:block">
                <div class="h-full rounded-full ${row.cer > 0.25 ? 'bg-red-500' : row.cer > 0.12 ? 'bg-amber-500' : 'bg-emerald-500'}" style="width: ${cerPct}%"></div>
              </div>
            </div>
          </td>
          <td class="py-4 text-right font-mono font-semibold">
            <span class="px-2 py-0.5 text-xs rounded-lg border ${werColor}">${pct(row.wer)}</span>
          </td>
          <td class="py-4 text-right font-mono text-slate-200">
            <span class="px-2 py-0.5 text-xs rounded-lg bg-slate-900 border border-slate-800">${row.mean_latency_s.toFixed(2)}s</span>
          </td>
          <td class="py-4 text-right font-mono text-slate-400 hidden sm:table-cell">
            ${pct(row.coverage)}
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    function sortLeaderboard(col) {
      if (leaderboardSortCol === col) {
        leaderboardSortAsc = !leaderboardSortAsc;
      } else {
        leaderboardSortCol = col;
        leaderboardSortAsc = col === 'model' ? true : true; // Default ascending (lower score is better, etc.)
      }
      renderLeaderboard();
    }

    function openModelExplorer(modelName) {
      document.getElementById('filter-model').value = modelName;
      applyFilters();
      switchTab('explorer');
    }

    // 2. Chart.js Domain analysis logic
    const domainLabels = Object.keys(byDomainData[0].domains);
    const domainCleanLabels = domainLabels.map(capitalize);

    // Color palette for chart lines
    const chartColors = [
      'rgb(99, 102, 241)',   // Indigo
      'rgb(168, 85, 247)',   // Purple
      'rgb(244, 63, 94)',    // Rose
      'rgb(16, 185, 129)',   // Emerald
      'rgb(245, 158, 11)',   // Amber
      'rgb(6, 182, 212)',    // Cyan
      'rgb(236, 72, 153)',   // Pink
      'rgb(234, 179, 8)'     // Yellow
    ];

    function initChartFilters() {
      const container = document.getElementById('model-checkboxes');
      container.innerHTML = '';
      
      // select top 4 models by default to prevent chart clutter
      const sortedByCer = [...leaderboardData].sort((a, b) => a.cer - b.cer);
      const top4Models = sortedByCer.slice(0, 4).map(x => x.model);
      selectedModelsForChart = [...top4Models];

      leaderboardData.forEach((row, idx) => {
        const color = chartColors[idx % chartColors.length];
        
        const label = document.createElement('label');
        label.className = "flex items-center gap-2 p-1.5 rounded-lg hover:bg-slate-900/60 cursor-pointer text-xs select-none border border-transparent hover:border-slate-800 transition";
        
        const checked = selectedModelsForChart.includes(row.model) ? 'checked' : '';
        
        label.innerHTML = `
          <input type="checkbox" ${checked} onchange="toggleChartModel('${row.model}')" class="rounded text-indigo-600 bg-slate-900 border-slate-700 focus:ring-indigo-500 focus:ring-offset-slate-900">
          <span style="border-bottom: 2px solid ${color}" class="text-slate-200 truncate pr-1">${capitalize(row.model)}</span>
        `;
        container.appendChild(label);
      });
    }

    function toggleChartModel(model) {
      const idx = selectedModelsForChart.indexOf(model);
      if (idx > -1) {
        selectedModelsForChart.splice(idx, 1);
      } else {
        selectedModelsForChart.push(model);
      }
      renderDomainChart();
    }

    // Update Chart Type
    function updateChartType() {
      chartType = document.getElementById('chart-type-select').value;
      if (chartType === 'radar') {
        document.getElementById('chart-title').innerText = "Model Performance Radar";
      } else {
        document.getElementById('chart-title').innerText = "Domain CER Comparison";
      }
      renderDomainChart();
    }

    function renderDomainChart() {
      if (domainChartInstance) {
        domainChartInstance.destroy();
      }

      const datasets = selectedModelsForChart.map(model => {
        const modelData = byDomainData.find(x => x.model === model);
        const dataValues = domainLabels.map(domain => modelData.domains[domain]);
        const modelIndex = leaderboardData.findIndex(x => x.model === model);
        const color = chartColors[modelIndex % chartColors.length];

        return {
          label: capitalize(model),
          data: dataValues,
          backgroundColor: chartType === 'radar' ? color.replace('rgb', 'rgba').replace(')', ', 0.15)') : color,
          borderColor: color,
          borderWidth: chartType === 'radar' ? 2 : 0,
          pointBackgroundColor: color,
          pointBorderColor: '#fff',
          pointHoverBackgroundColor: '#fff',
          pointHoverBorderColor: color,
          borderRadius: chartType === 'bar' ? 4 : 0
        };
      });

      const ctx = document.getElementById('domain-chart').getContext('2d');
      
      const config = {
        type: chartType,
        data: {
          labels: domainCleanLabels,
          datasets: datasets
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: false // We use our own label checkboxes below
            },
            tooltip: {
              backgroundColor: 'rgba(15, 23, 42, 0.95)',
              titleColor: '#fff',
              bodyColor: '#cbd5e1',
              borderColor: 'rgba(255, 255, 255, 0.08)',
              borderWidth: 1,
              padding: 10,
              callbacks: {
                label: function(context) {
                  return ` ${context.dataset.label}: ${(context.raw * 100).toFixed(2)}% CER`;
                }
              }
            }
          },
          scales: chartType === 'radar' ? {
            r: {
              grid: {
                color: 'rgba(148, 163, 184, 0.1)'
              },
              angleLines: {
                color: 'rgba(148, 163, 184, 0.1)'
              },
              pointLabels: {
                color: '#94a3b8',
                font: {
                  family: 'Outfit',
                  size: 9
                }
              },
              ticks: {
                backdropColor: 'transparent',
                color: '#64748b',
                font: {
                  size: 8
                },
                callback: function(val) {
                  return (val * 100).toFixed(0) + '%';
                }
              },
              min: 0,
              max: 0.5 // capping at 50% CER for visualization resolution
            }
          } : {
            x: {
              grid: {
                display: false
              },
              ticks: {
                color: '#94a3b8',
                font: {
                  family: 'Outfit',
                  size: 9
                }
              }
            },
            y: {
              grid: {
                color: 'rgba(148, 163, 184, 0.06)'
              },
              ticks: {
                color: '#64748b',
                font: {
                  size: 9
                },
                callback: function(val) {
                  return (val * 100).toFixed(0) + '%';
                }
              }
            }
          }
        }
      };

      domainChartInstance = new Chart(ctx, config);
    }

    // 3. Domain Heatmap logic
    function renderHeatmap() {
      const headerTr = document.querySelector('#heatmap-table tr');
      // Remove all headers except the first "Model" header
      while (headerTr.children.length > 1) {
        headerTr.removeChild(headerTr.lastChild);
      }
      
      domainCleanLabels.forEach(label => {
        const th = document.createElement('th');
        th.className = "p-3 font-semibold text-slate-300 text-xs tracking-wider uppercase";
        th.innerText = label;
        headerTr.appendChild(th);
      });

      const tbody = document.getElementById('heatmap-body');
      tbody.innerHTML = '';

      byDomainData.forEach(row => {
        const tr = document.createElement('tr');
        tr.className = "hover:bg-slate-900/20 border-b border-slate-800/40";
        
        let modelTd = document.createElement('td');
        modelTd.className = "p-3 font-semibold text-white sticky left-0 bg-slate-950/90 z-10 border-r border-slate-800";
        modelTd.innerText = capitalize(row.model);
        tr.appendChild(modelTd);

        domainLabels.forEach(domain => {
          const val = row.domains[domain];
          const td = document.createElement('td');
          td.className = "p-3 text-center font-mono text-xs select-all font-semibold transition-all";
          td.innerText = val ? pct(val) : '-';
          
          // Color shading based on value
          // Green for perfect accuracy, scaling up to Red for poor accuracy
          if (val === 0) {
            td.style.backgroundColor = 'rgba(16, 185, 129, 0.25)'; // Emerald 500
            td.style.color = '#34d399';
          } else if (val < 0.05) {
            td.style.backgroundColor = 'rgba(16, 185, 129, 0.18)';
            td.style.color = '#34d399';
          } else if (val < 0.10) {
            td.style.backgroundColor = 'rgba(16, 185, 129, 0.1)';
            td.style.color = '#6ee7b7';
          } else if (val < 0.20) {
            td.style.backgroundColor = 'rgba(245, 158, 11, 0.1)'; // Amber 500
            td.style.color = '#fcd34d';
          } else if (val < 0.35) {
            td.style.backgroundColor = 'rgba(244, 63, 94, 0.1)'; // Rose 500
            td.style.color = '#rose-300';
          } else {
            td.style.backgroundColor = 'rgba(244, 63, 94, 0.22)';
            td.style.color = '#f43f5e';
          }
          
          tr.appendChild(td);
        });

        tbody.appendChild(tr);
      });
    }

    // 4. Utterance Explorer Filters & Pagination
    function initExplorerFilters() {
      // Model dropdown options
      const modelSelect = document.getElementById('filter-model');
      leaderboardData.forEach(row => {
        const opt = document.createElement('option');
        opt.value = row.model;
        opt.innerText = capitalize(row.model);
        modelSelect.appendChild(opt);
      });

      // Domain dropdown options
      const domainSelect = document.getElementById('filter-domain');
      domainLabels.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d;
        opt.innerText = capitalize(d);
        domainSelect.appendChild(opt);
      });
    }

    function applyFilters() {
      const modelVal = document.getElementById('filter-model').value;
      const domainVal = document.getElementById('filter-domain').value;
      const cerVal = document.getElementById('filter-cer').value;
      const searchVal = document.getElementById('filter-search').value.toLowerCase().trim();

      filteredRecords = perFileData.filter(row => {
        // Model filter
        if (modelVal !== 'all' && row.model !== modelVal) return false;
        
        // Domain filter
        if (domainVal !== 'all' && row.domain !== domainVal) return false;

        // CER filter
        if (cerVal === 'perfect' && row.cer > 0) return false;
        if (cerVal === 'errors' && row.cer === 0) return false;
        if (cerVal === 'low' && (row.cer === 0 || row.cer > 0.10)) return false;
        if (cerVal === 'mid' && (row.cer <= 0.10 || row.cer > 0.30)) return false;
        if (cerVal === 'high' && row.cer <= 0.30) return false;

        // Search text / file
        if (searchVal) {
          const inPath = row.file_path.toLowerCase().includes(searchVal);
          const inRef = row.ref.toLowerCase().includes(searchVal);
          const inHyp = row.hyp.toLowerCase().includes(searchVal);
          if (!inPath && !inRef && !inHyp) return false;
        }

        return true;
      });

      // Sort Explorer filtered output
      sortExplorerData();
      
      currentPage = 1;
      renderExplorerTable();
    }

    function sortExplorerData() {
      filteredRecords.sort((a, b) => {
        let valA = a[explorerSortCol];
        let valB = b[explorerSortCol];
        return explorerSortAsc ? valA - valB : valB - valA;
      });
    }

    function toggleSortExplorer(col) {
      if (explorerSortCol === col) {
        explorerSortAsc = !explorerSortAsc;
      } else {
        explorerSortCol = col;
        explorerSortAsc = false; // Default descending (worst errors first)
      }
      sortExplorerData();
      currentPage = 1;
      renderExplorerTable();
    }

    function renderExplorerTable() {
      const tbody = document.getElementById('explorer-body');
      tbody.innerHTML = '';

      const total = filteredRecords.length;
      document.getElementById('explorer-counter').innerText = `Found ${total} matching utterances`;

      if (total === 0) {
        document.getElementById('explorer-empty').classList.remove('hidden');
        document.getElementById('page-start').innerText = 0;
        document.getElementById('page-end').innerText = 0;
        document.getElementById('page-total').innerText = 0;
        renderPagination(0);
        return;
      }

      document.getElementById('explorer-empty').classList.add('hidden');

      // Pagination math
      const totalPages = Math.ceil(total / itemsPerPage);
      if (currentPage > totalPages) currentPage = totalPages;
      if (currentPage < 1) currentPage = 1;

      const startIndex = (currentPage - 1) * itemsPerPage;
      const endIndex = Math.min(startIndex + itemsPerPage, total);

      document.getElementById('page-start').innerText = startIndex + 1;
      document.getElementById('page-end').innerText = endIndex;
      document.getElementById('page-total').innerText = total;

      const pageData = filteredRecords.slice(startIndex, endIndex);

      pageData.forEach(row => {
        const tr = document.createElement('tr');
        tr.className = "hover:bg-slate-900/30 transition border-b border-slate-800/40 align-middle";
        
        let cerColor = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
        if (row.cer > 0.30) cerColor = 'text-red-400 bg-red-500/10 border-red-500/20';
        else if (row.cer > 0.05) cerColor = 'text-amber-400 bg-amber-500/10 border-amber-500/20';

        let werColor = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
        if (row.wer > 0.40) werColor = 'text-red-400 bg-red-500/10 border-red-500/20';
        else if (row.wer > 0.15) werColor = 'text-amber-400 bg-amber-500/10 border-amber-500/20';

        const filename = row.file_path.split('/').pop();

        // Create row html. We pass index to identify the row data directly from pageData.
        const rowDataStr = JSON.stringify({
          model: row.model,
          domain: row.domain,
          file_path: row.file_path,
          cer: row.cer,
          wer: row.wer,
          ref: row.ref,
          hyp: row.hyp
        }).replace(/"/g, '&quot;');

        tr.innerHTML = `
          <td class="p-4 font-semibold text-slate-100">${capitalize(row.model)}</td>
          <td class="p-4"><span class="px-2 py-0.5 text-xs bg-slate-800 text-slate-400 rounded-md border border-slate-700">${capitalize(row.domain)}</span></td>
          <td class="p-4 font-mono text-xs text-slate-400 hidden md:table-cell max-w-[150px] truncate" title="${row.file_path}">${filename}</td>
          <td class="p-4 text-center font-mono">
            <span class="px-2 py-0.5 text-xs rounded-lg border ${cerColor}">${pct(row.cer)}</span>
          </td>
          <td class="p-4 text-center font-mono">
            <span class="px-2 py-0.5 text-xs rounded-lg border ${werColor}">${pct(row.wer)}</span>
          </td>
          <td class="p-4 max-w-sm truncate leading-relaxed">
            <div class="text-xs text-slate-400 flex items-center gap-1.5"><span class="font-bold text-[10px] text-slate-500 uppercase tracking-wider">Ref:</span> ${row.ref}</div>
            <div class="text-xs text-slate-200 mt-1 flex items-center gap-1.5"><span class="font-bold text-[10px] text-slate-500 uppercase tracking-wider">Hyp:</span> ${row.hyp}</div>
          </td>
          <td class="p-4 text-center">
            <button onclick="openDetailsFromData('${rowDataStr}')" class="px-3 py-1.5 bg-indigo-600/20 hover:bg-indigo-600 text-indigo-300 hover:text-white rounded-lg text-xs font-semibold border border-indigo-500/30 transition shadow-sm">
              Inspect
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      renderPagination(totalPages);
    }

    function renderPagination(totalPages) {
      const container = document.getElementById('pagination-pages');
      container.innerHTML = '';

      if (totalPages <= 1) return;

      // Logic to show a max of 5 page buttons
      let start = Math.max(1, currentPage - 2);
      let end = Math.min(totalPages, start + 4);
      if (end - start < 4) {
        start = Math.max(1, end - 4);
      }

      for (let i = start; i <= end; i++) {
        const btn = document.createElement('button');
        btn.onclick = () => {
          currentPage = i;
          renderExplorerTable();
        };
        
        if (i === currentPage) {
          btn.className = "px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white shadow";
        } else {
          btn.className = "px-3 py-1.5 text-xs font-medium rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-900 transition";
        }
        btn.innerText = i;
        container.appendChild(btn);
      }
    }

    function prevPage() {
      if (currentPage > 1) {
        currentPage--;
        renderExplorerTable();
      }
    }

    function nextPage() {
      const totalPages = Math.ceil(filteredRecords.length / itemsPerPage);
      if (currentPage < totalPages) {
        currentPage++;
        renderExplorerTable();
      }
    }

    // 5. Detailed Modal with Dynamic Word Diff
    function openDetailsFromData(rowDataStr) {
      const row = JSON.parse(rowDataStr);
      openDetails(row);
    }

    function openDetails(row) {
      document.getElementById('modal-model-badge').innerText = capitalize(row.model);
      document.getElementById('modal-domain-badge').innerText = capitalize(row.domain);
      document.getElementById('modal-title-file').innerText = row.file_path.split('/').pop();
      document.getElementById('modal-path').innerText = row.file_path;
      document.getElementById('modal-cer').innerText = pct(row.cer);
      document.getElementById('modal-wer').innerText = pct(row.wer);
      document.getElementById('modal-ref').innerText = row.ref;
      document.getElementById('modal-hyp').innerText = row.hyp;

      // Set audio source
      const player = document.getElementById('modal-audio-player');
      // Relative from results/dashboard.html to root is "../"
      player.src = `../wavs${row.file_path}`;

      // Calculate and render word diff
      const diffContainer = document.getElementById('modal-diff');
      diffContainer.innerHTML = '';
      
      const diffResult = diffWords(row.ref, row.hyp);
      diffResult.forEach(item => {
        const span = document.createElement('span');
        span.className = "inline-block px-1 rounded py-0.5 mx-0.5 text-base font-medium select-all transition-all";
        
        if (item.type === 'equal') {
          span.className += " text-slate-200 hover:bg-slate-800";
          span.innerText = item.value;
        } else if (item.type === 'delete') {
          span.className += " bg-red-500/20 text-red-400 line-through border border-red-500/20";
          span.innerText = item.value;
          span.title = "Deleted / Missing in transcription";
        } else if (item.type === 'insert') {
          span.className += " bg-emerald-500/20 text-emerald-400 border border-emerald-500/20";
          span.innerText = item.value;
          span.title = "Inserted / Extra in transcription";
        }
        diffContainer.appendChild(span);
      });

      // Show modal
      document.getElementById('details-modal').classList.remove('hidden');
      document.body.style.overflow = 'hidden';
    }

    function closeModal() {
      // Pause audio playback
      const player = document.getElementById('modal-audio-player');
      player.pause();
      
      document.getElementById('details-modal').classList.add('hidden');
      document.body.style.overflow = 'auto';
    }

    // Dynamic LCS Word-Level Diff Algorithm
    function diffWords(ref, hyp) {
      // Remove common punctuation and clean strings for diffing
      const cleanWord = (w) => w.replace(/[.,\/#!$%\^&\*;:{}=\-_`~()?।]/g, "").trim();

      const refWords = ref.trim().split(/\s+/).filter(Boolean);
      const hypWords = hyp.trim().split(/\s+/).filter(Boolean);
      
      const n = refWords.length;
      const m = hypWords.length;
      
      // dp table
      const dp = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));
      
      for (let i = 1; i <= n; i++) {
        for (let j = 1; j <= m; j++) {
          if (cleanWord(refWords[i - 1]) === cleanWord(hypWords[j - 1])) {
            dp[i][j] = dp[i - 1][j - 1] + 1;
          } else {
            dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
          }
        }
      }
      
      let i = n, j = m;
      const result = [];
      
      while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && cleanWord(refWords[i - 1]) === cleanWord(hypWords[j - 1])) {
          result.push({ type: 'equal', value: hypWords[j - 1] }); // prefer actual output spacing/punctuation
          i--;
          j--;
        } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
          result.push({ type: 'insert', value: hypWords[j - 1] });
          j--;
        } else {
          result.push({ type: 'delete', value: refWords[i - 1] });
          i--;
        }
      }
      
      return result.reverse();
    }

    // On Load
    window.addEventListener('DOMContentLoaded', () => {
      // Initial render calls
      renderLeaderboard();
      initChartFilters();
      renderDomainChart();
      renderHeatmap();
      initExplorerFilters();
      applyFilters();
    });
  </script>
</body>
</html>
"""

    # Substitute JSON outputs into template
    html_content = html_template.replace("%GLOBAL_STATS_JSON%", json.dumps(global_stats))
    html_content = html_content.replace("%LEADERBOARD_JSON%", json.dumps(leaderboard))
    html_content = html_content.replace("%BY_DOMAIN_JSON%", json.dumps(by_domain))
    html_content = html_content.replace("%PER_FILE_JSON%", json.dumps(per_file))

    print(f"Writing dashboard to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print("Success! Dashboard has been successfully generated.")
    print("You can view it by double-clicking on the file:")
    print(f"  file://{output_path}")

if __name__ == "__main__":
    main()
