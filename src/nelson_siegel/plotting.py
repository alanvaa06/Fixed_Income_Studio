"""
Plotting and Visualization Module

This module provides plotting functionality for yield curves, factors,
and comparative analysis visualizations.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import Dict, Optional, List, Tuple, Union



class YieldCurvePlotter:
    """
    Plotting utilities for yield curve analysis and Nelson-Siegel factors.
    """
    
    def __init__(self, style: str = 'seaborn-v0_8', figsize: Tuple[int, int] = (12, 8)):
        """
        Initialize the plotter.
        
        Parameters:
        -----------
        style : str
            Matplotlib style to use
        figsize : tuple
            Default figure size
        """
        try:
            plt.style.use(style)
        except:
            plt.style.use('default')
        
        self.default_figsize = figsize
        self.colors = {
            'treasury': '#1f77b4',  # Blue
            'tips': '#ff7f0e',      # Orange
            'fitted': '#d62728',    # Red
            'observed': '#2ca02c'   # Green
        }
    
    def plot_yield_curve_fit(self, 
                           analysis_result: Dict,
                           title: Optional[str] = None,
                           save_path: Optional[str] = None,
                           show_deviations: bool = True) -> plt.Figure:
        """
        Plot observed vs fitted yield curve with deviations.
        
        Parameters:
        -----------
        analysis_result : dict
            Result from YieldCurveAnalyzer.analyze_single_curve()
        title : str, optional
            Custom plot title
        save_path : str, optional
            Path to save the plot
        show_deviations : bool
            Whether to show deviation subplot
        
        Returns:
        --------
        matplotlib.figure.Figure
            The created figure
        """
        if show_deviations:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=self.default_figsize, 
                                          height_ratios=[3, 1], sharex=True)
        else:
            fig, ax1 = plt.subplots(1, 1, figsize=self.default_figsize)
        
        # Main yield curve plot
        maturities = analysis_result['maturities']
        observed = analysis_result['observed_yields'] * 100  # Convert to percentage
        fitted = analysis_result['fitted_yields'] * 100
        smooth_mat = analysis_result['smooth_maturities']
        smooth_fit = analysis_result['smooth_fitted'] * 100
        
        # Plot points and curves
        ax1.scatter(maturities, observed, color=self.colors['observed'], 
                   s=60, label='Observed Yields', zorder=5, alpha=0.8)
        ax1.plot(smooth_mat, smooth_fit, color=self.colors['fitted'], 
                linewidth=2.5, label='Nelson-Siegel Fit', zorder=4)
        ax1.scatter(maturities, fitted, color=self.colors['fitted'], 
                   s=40, alpha=0.7, zorder=6)
        
        # Formatting
        ax1.set_ylabel('Yield (%)', fontsize=12)
        ax1.set_title(title or f"{analysis_result['bond_type'].upper()} Yield Curve - {analysis_result.get('date', 'Current')}", 
                     fontsize=14, fontweight='bold')
        ax1.legend(fontsize=11)
        ax1.grid(True, alpha=0.3)
        
        # Add factor information
        factors = analysis_result['factors']
        rmse = analysis_result['rmse'] * 100
        
        info_text = (f"Level: {factors['Level']*100:.2f}%\n"
                    f"Slope: {factors['Slope']*100:.2f}%\n" 
                    f"Curvature: {factors['Curvature']*100:.2f}%\n"
                    f"Tau: {factors['Tau']:.2f}\n"
                    f"RMSE: {rmse:.2f} bps")
        
        ax1.text(0.02, 0.98, info_text, transform=ax1.transAxes, 
                verticalalignment='top', fontsize=10, 
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        if show_deviations:
            # Deviation subplot
            deviations = analysis_result['deviations'] * 10000  # Convert to basis points
            colors = ['red' if d > 0 else 'green' for d in deviations]
            
            bars = ax2.bar(maturities, deviations, color=colors, alpha=0.7)
            ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.8)
            ax2.set_xlabel('Maturity (Years)', fontsize=12)
            ax2.set_ylabel('Deviation (bps)', fontsize=12)
            ax2.set_title('Actual - Fitted Yields', fontsize=12)
            ax2.grid(True, alpha=0.3)
            
            # Add cheap/expensive labels
            classifications = analysis_result['bond_classification']
            for i, (mat, dev, cls) in enumerate(zip(maturities, deviations, classifications)):
                ax2.text(mat, dev + (2 if dev >= 0 else -8), cls.upper(), 
                        ha='center', fontsize=9, fontweight='bold',
                        color='darkred' if cls == 'expensive' else 'darkgreen')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Plot saved to: {save_path}")
        
        return fig
    
    def plot_historical_factors(self, 
                              factors: pd.DataFrame,
                              bond_type: str,
                              title: Optional[str] = None,
                              save_path: Optional[str] = None) -> plt.Figure:
        """
        Plot historical evolution of Nelson-Siegel factors.
        
        Parameters:
        -----------
        factors : pd.DataFrame
            Historical factors with columns [Level, Slope, Curvature, Tau]
        bond_type : str
            Bond type for labeling
        title : str, optional
            Custom plot title
        save_path : str, optional
            Path to save the plot
        
        Returns:
        --------
        matplotlib.figure.Figure
            The created figure
        """
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        axes = axes.ravel()
        
        factor_names = ['Level', 'Slope', 'Curvature', 'Tau']
        factor_units = ['%', '%', '%', 'Years']
        
        for i, factor in enumerate(factor_names):
            if factor in factors.columns:
                data = factors[factor]
                if factor != 'Tau':
                    data = data * 100  # Convert to percentage
                
                axes[i].plot(factors.index, data, linewidth=1.5, 
                           color=self.colors.get(bond_type.lower(), '#1f77b4'))
                axes[i].set_title(f'{bond_type.upper()} - {factor} Factor', 
                                fontsize=12, fontweight='bold')
                axes[i].set_ylabel(f'{factor} ({factor_units[i]})', fontsize=11)
                axes[i].grid(True, alpha=0.3)
                
                # Format x-axis
                axes[i].tick_params(axis='x', rotation=45)
                if len(factors) > 100:
                    axes[i].xaxis.set_major_locator(mdates.YearLocator())
                    axes[i].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
                
                # Add statistics
                mean_val = data.mean()
                std_val = data.std()
                axes[i].axhline(y=mean_val, color='red', linestyle='--', alpha=0.7, linewidth=1)
                axes[i].text(0.02, 0.98, f'Mean: {mean_val:.2f}\nStd: {std_val:.2f}', 
                           transform=axes[i].transAxes, verticalalignment='top',
                           fontsize=9, bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        plt.suptitle(title or f'{bond_type.upper()} Nelson-Siegel Factors Evolution', 
                    fontsize=16, fontweight='bold')
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Plot saved to: {save_path}")
        
        return fig
    
    def plot_factor_comparison(self, 
                             treasury_factors: pd.DataFrame,
                             tips_factors: pd.DataFrame,
                             title: Optional[str] = None,
                             save_path: Optional[str] = None) -> plt.Figure:
        """
        Compare Treasury and TIPS factors side by side.
        
        Parameters:
        -----------
        treasury_factors : pd.DataFrame
            Treasury historical factors
        tips_factors : pd.DataFrame
            TIPS historical factors  
        title : str, optional
            Custom plot title
        save_path : str, optional
            Path to save the plot
        
        Returns:
        --------
        matplotlib.figure.Figure
            The created figure
        """
        # Align data to common dates
        common_dates = treasury_factors.index.intersection(tips_factors.index)
        
        if len(common_dates) == 0:
            raise ValueError("No common dates found between Treasury and TIPS factors")
        
        tsy_aligned = treasury_factors.loc[common_dates]
        tips_aligned = tips_factors.loc[common_dates]
        
        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        axes = axes.ravel()
        
        factor_names = ['Level', 'Slope', 'Curvature', 'Tau']
        factor_units = ['%', '%', '%', 'Years']
        
        for i, factor in enumerate(factor_names):
            if factor in tsy_aligned.columns and factor in tips_aligned.columns:
                tsy_data = tsy_aligned[factor]
                tips_data = tips_aligned[factor]
                
                if factor != 'Tau':
                    tsy_data = tsy_data * 100
                    tips_data = tips_data * 100
                
                axes[i].plot(common_dates, tsy_data, linewidth=2, 
                           color=self.colors['treasury'], label='Treasury (Nominal)', alpha=0.8)
                axes[i].plot(common_dates, tips_data, linewidth=2, 
                           color=self.colors['tips'], label='TIPS (Real)', alpha=0.8)
                
                axes[i].set_title(f'{factor} Factor Comparison', fontsize=12, fontweight='bold')
                axes[i].set_ylabel(f'{factor} ({factor_units[i]})', fontsize=11)
                axes[i].legend(fontsize=10)
                axes[i].grid(True, alpha=0.3)
                axes[i].tick_params(axis='x', rotation=45)
                
                # Format x-axis
                if len(common_dates) > 100:
                    axes[i].xaxis.set_major_locator(mdates.YearLocator())
                    axes[i].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
                
                # Add correlation information
                correlation = tsy_data.corr(tips_data)
                axes[i].text(0.02, 0.98, f'Correlation: {correlation:.3f}', 
                           transform=axes[i].transAxes, verticalalignment='top',
                           fontsize=9, bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
        
        plt.suptitle(title or 'Treasury vs TIPS Nelson-Siegel Factors', 
                    fontsize=16, fontweight='bold')
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Plot saved to: {save_path}")
        
        return fig
    
    def plot_yield_surface(self, 
                          factors_df: pd.DataFrame,
                          bond_type: str,
                          factor_name: str = 'Level',
                          save_path: Optional[str] = None) -> plt.Figure:
        """
        Plot 3D surface of a factor over time and maturity.
        
        Parameters:
        -----------
        factors_df : pd.DataFrame
            Historical factors
        bond_type : str
            Bond type for labeling
        factor_name : str
            Which factor to plot ('Level', 'Slope', 'Curvature', 'Tau')
        save_path : str, optional
            Path to save the plot
        
        Returns:
        --------
        matplotlib.figure.Figure
            The created figure
        """
        fig = plt.figure(figsize=(14, 8))
        ax = fig.add_subplot(111, projection='3d')
        
        # Prepare data
        if factor_name not in factors_df.columns:
            raise ValueError(f"Factor '{factor_name}' not found in data")
        
        factor_data = factors_df[factor_name]
        if factor_name != 'Tau':
            factor_data = factor_data * 100
        
        # Create meshgrid for surface plot
        dates_numeric = mdates.date2num(factor_data.index)
        
        # Sample data for surface (using rolling windows)
        window_size = max(1, len(factor_data) // 50)  # Sample every N points
        sampled_dates = dates_numeric[::window_size]
        sampled_values = factor_data.iloc[::window_size].values
        
        # Plot as line plot in 3D space
        ax.plot(sampled_dates, np.zeros_like(sampled_dates), sampled_values, 
               linewidth=2, color=self.colors.get(bond_type.lower(), '#1f77b4'))
        
        ax.set_xlabel('Date', fontsize=11)
        ax.set_ylabel('', fontsize=11) 
        ax.set_zlabel(f'{factor_name} ({"%" if factor_name != "Tau" else "Years"})', fontsize=11)
        ax.set_title(f'{bond_type.upper()} {factor_name} Factor Evolution', 
                    fontsize=14, fontweight='bold')
        
        # Format date axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Plot saved to: {save_path}")
        
        return fig
    
    def create_summary_dashboard(self, 
                               comparison_result: Dict,
                               save_path: Optional[str] = None) -> plt.Figure:
        """
        Create a comprehensive dashboard with multiple plots.
        
        Parameters:
        -----------
        comparison_result : dict
            Result from YieldCurveAnalyzer.compare_curves()
        save_path : str, optional
            Path to save the dashboard
        
        Returns:
        --------
        matplotlib.figure.Figure
            The created dashboard figure
        """
        fig = plt.figure(figsize=(20, 12))
        
        # Factor comparison plots (top row)
        for i, factor in enumerate(['Level', 'Slope', 'Curvature', 'Tau']):
            ax = plt.subplot(3, 4, i + 1)
            
            tsy_data = comparison_result['treasury_aligned'][factor]
            tips_data = comparison_result['tips_aligned'][factor]
            
            if factor != 'Tau':
                tsy_data = tsy_data * 100
                tips_data = tips_data * 100
            
            ax.plot(tsy_data.index, tsy_data, linewidth=1.5, 
                   color=self.colors['treasury'], label='Treasury', alpha=0.8)
            ax.plot(tips_data.index, tips_data, linewidth=1.5, 
                   color=self.colors['tips'], label='TIPS', alpha=0.8)
            
            ax.set_title(f'{factor} Factor', fontsize=11, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.tick_params(axis='x', rotation=45, labelsize=8)
            ax.tick_params(axis='y', labelsize=8)
            
            if i == 0:
                ax.legend(fontsize=9)
        
        # Correlation matrix (middle left)
        ax_corr = plt.subplot(3, 4, 5)
        correlations = comparison_result['correlations']
        factors = list(correlations.keys())
        corr_values = [correlations[f] for f in factors]
        
        bars = ax_corr.bar(factors, corr_values, color=['lightblue', 'lightgreen', 'lightcoral', 'lightyellow'])
        ax_corr.set_title('Factor Correlations (TSY vs TIPS)', fontsize=11, fontweight='bold')
        ax_corr.set_ylabel('Correlation', fontsize=10)
        ax_corr.set_ylim(-1, 1)
        ax_corr.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        ax_corr.grid(True, alpha=0.3)
        
        # Add correlation values on bars
        for bar, val in zip(bars, corr_values):
            ax_corr.text(bar.get_x() + bar.get_width()/2, val + 0.05 if val >= 0 else val - 0.05,
                        f'{val:.3f}', ha='center', va='bottom' if val >= 0 else 'top', fontsize=9)
        
        # Difference statistics (middle right)
        ax_diff = plt.subplot(3, 4, 6)
        diff_data = comparison_result['differences']
        factor_names = list(diff_data.keys())
        mean_diffs = [diff_data[f]['mean_diff'] * (100 if f != 'Tau' else 1) for f in factor_names]
        
        colors_diff = ['red' if d > 0 else 'blue' for d in mean_diffs]
        bars_diff = ax_diff.bar(factor_names, mean_diffs, color=colors_diff, alpha=0.7)
        ax_diff.set_title('Mean Differences (TSY - TIPS)', fontsize=11, fontweight='bold')
        ax_diff.set_ylabel('Difference', fontsize=10)
        ax_diff.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        ax_diff.grid(True, alpha=0.3)
        
        # Summary statistics table (bottom)
        ax_table = plt.subplot(3, 1, 3)
        ax_table.axis('off')
        
        # Create summary table data
        table_data = []
        headers = ['Factor', 'TSY Mean', 'TIPS Mean', 'Difference', 'Correlation', 'TSY Std', 'TIPS Std']
        
        for factor in factor_names:
            diff_info = diff_data[factor]
            corr = correlations[factor]
            
            multiplier = 100 if factor != 'Tau' else 1
            unit = '%' if factor != 'Tau' else ''
            
            row = [
                factor,
                f"{diff_info['mean_tsy'] * multiplier:.2f}{unit}",
                f"{diff_info['mean_tips'] * multiplier:.2f}{unit}",
                f"{diff_info['mean_diff'] * multiplier:.2f}{unit}",
                f"{corr:.3f}",
                f"{diff_info['std_tsy'] * multiplier:.2f}{unit}",
                f"{diff_info['std_tips'] * multiplier:.2f}{unit}"
            ]
            table_data.append(row)
        
        table = ax_table.table(cellText=table_data, colLabels=headers,
                              cellLoc='center', loc='center',
                              bbox=[0.1, 0.1, 0.8, 0.8])
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 2)
        
        # Style the table
        for i in range(len(headers)):
            table[(0, i)].set_facecolor('#40466e')
            table[(0, i)].set_text_props(weight='bold', color='white')
        
        plt.suptitle('Treasury vs TIPS Yield Curve Analysis Dashboard', 
                    fontsize=16, fontweight='bold', y=0.98)
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Dashboard saved to: {save_path}")
        
        return fig
