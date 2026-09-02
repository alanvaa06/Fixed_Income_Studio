"""
Interactive Widgets Module for Nelson-Siegel Analysis

This module provides interactive Jupyter notebook widgets for exploring
Nelson-Siegel yield curve parameters and their economic interpretations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import Dict, Optional, Tuple, List

# Handle optional ipywidgets import
try:
    import ipywidgets as widgets
    from IPython.display import display, HTML
    HAS_IPYWIDGETS = True
except ImportError:
    HAS_IPYWIDGETS = False  # the package-level import guard reports this

from .model import NelsonSiegelModel, TreasuryNelsonSiegelModel, TIPSNelsonSiegelModel
from .data import DataManager



class InteractiveYieldCurveExplorer:
    """
    Interactive yield curve explorer with educational widgets.
    
    This class provides interactive controls for exploring how Nelson-Siegel
    parameters affect yield curve shapes and their economic interpretations.
    """
    
    def __init__(self, bond_type: str = 'treasury', fred_api_key: Optional[str] = None):
        """
        Initialize the interactive explorer.
        
        Parameters:
        -----------
        bond_type : str
            'treasury' or 'tips'
        fred_api_key : str, optional
            FRED API key for real data access
        """
        if not HAS_IPYWIDGETS:
            raise ImportError("ipywidgets is required for interactive functionality. "
                            "Install with: pip install ipywidgets")
        
        self.bond_type = bond_type.lower()
        self.data_manager = DataManager(fred_api_key)
        
        # Initialize model with appropriate bounds
        if self.bond_type == 'treasury':
            self.model = TreasuryNelsonSiegelModel()
            self.default_params = (0.045, -0.01, 0.005, 2.0)  # Realistic Treasury params
        else:
            self.model = TIPSNelsonSiegelModel()
            self.default_params = (0.015, -0.005, 0.002, 2.0)  # Realistic TIPS params
        
        # Standard maturity range for plotting
        self.plot_maturities = np.linspace(0.25, 30, 100)
        
        # Current market data placeholder
        self.current_yields = None
        self.current_maturities = None
        
    def load_current_data(self, date: Optional[str] = None) -> bool:
        """
        Load current market data for comparison.
        
        Parameters:
        -----------
        date : str, optional
            Date in 'YYYY-MM-DD' format. If None, uses latest data.
        
        Returns:
        --------
        bool
            True if data loaded successfully
        """
        try:
            if self.bond_type == 'treasury':
                data = self.data_manager.get_treasury_data()
            else:
                data = self.data_manager.get_tips_data()
            
            if date:
                date_obj = pd.to_datetime(date)
                if date_obj in data.index:
                    yields = data.loc[date_obj].dropna()
                else:
                    print(f"Date {date} not found, using latest data")
                    yields = data.iloc[-1].dropna()
            else:
                yields = data.iloc[-1].dropna()
            
            self.current_yields = yields.values
            self.current_maturities = yields.index.values
            return True
            
        except Exception as e:
            print(f"Could not load market data: {e}")
            return False
    
    def create_parameter_widgets(self) -> Dict[str, widgets.Widget]:
        """
        Create interactive parameter control widgets.
        
        Returns:
        --------
        dict
            Dictionary of parameter control widgets
        """
        # Determine appropriate ranges based on bond type
        if self.bond_type == 'treasury':
            level_range = (0.0, 0.1)  # 0-10%
            slope_range = (-0.05, 0.05)  # -5% to +5%
            curve_range = (-0.05, 0.05)  # -5% to +5%
        else:
            level_range = (-0.02, 0.08)  # -2% to +8% (TIPS can be negative)
            slope_range = (-0.05, 0.05)
            curve_range = (-0.05, 0.05)
        
        widgets_dict = {
            'level': widgets.FloatSlider(
                value=self.default_params[0],
                min=level_range[0],
                max=level_range[1],
                step=0.001,
                description='Level (β₀):',
                style={'description_width': 'initial'},
                continuous_update=True,
                readout_format='.3f'
            ),
            
            'slope': widgets.FloatSlider(
                value=self.default_params[1],
                min=slope_range[0],
                max=slope_range[1],
                step=0.001,
                description='Slope (β₁):',
                style={'description_width': 'initial'},
                continuous_update=True,
                readout_format='.3f'
            ),
            
            'curvature': widgets.FloatSlider(
                value=self.default_params[2],
                min=curve_range[0],
                max=curve_range[1],
                step=0.001,
                description='Curvature (β₂):',
                style={'description_width': 'initial'},
                continuous_update=True,
                readout_format='.3f'
            ),
            
            'tau': widgets.FloatSlider(
                value=self.default_params[3],
                min=0.1,
                max=10.0,
                step=0.1,
                description='Tau (λ):',
                style={'description_width': 'initial'},
                continuous_update=True,
                readout_format='.1f'
            ),
            
            'show_market': widgets.Checkbox(
                value=False,
                description='Show Market Data',
                style={'description_width': 'initial'}
            ),
            
            'show_components': widgets.Checkbox(
                value=False,
                description='Show Factor Components',
                style={'description_width': 'initial'}
            )
        }
        
        return widgets_dict
    
    def plot_interactive_curve(self, level: float, slope: float, curvature: float, 
                              tau: float, show_market: bool = False, 
                              show_components: bool = False):
        """
        Plot interactive yield curve with parameter controls.
        
        Parameters:
        -----------
        level : float
            Level parameter (β₀)
        slope : float
            Slope parameter (β₁)
        curvature : float
            Curvature parameter (β₂)
        tau : float
            Tau parameter (λ)
        show_market : bool
            Whether to show current market data
        show_components : bool
            Whether to show individual factor components
        """
        # Clear previous plots
        plt.clf()
        
        # Set up the plot
        if show_components:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
        else:
            fig, ax1 = plt.subplots(1, 1, figsize=(12, 6))
        
        # Calculate Nelson-Siegel curve
        ns_yields = NelsonSiegelModel.model_function(self.plot_maturities, level, slope, curvature, tau)
        
        # Main yield curve plot
        ax1.plot(self.plot_maturities, ns_yields * 100, 'b-', linewidth=3, 
                label=f'{self.bond_type.upper()} Nelson-Siegel Curve', alpha=0.8)
        
        # Show market data if available and requested
        if show_market and self.current_yields is not None:
            ax1.scatter(self.current_maturities, self.current_yields * 100, 
                       color='red', s=60, label='Current Market Data', zorder=5, alpha=0.8)
        
        # Formatting
        ax1.set_xlabel('Maturity (Years)', fontsize=12)
        ax1.set_ylabel('Yield (%)', fontsize=12)
        ax1.set_title(f'{self.bond_type.upper()} Yield Curve - Nelson-Siegel Model', 
                     fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.legend(fontsize=11)
        
        # Add parameter info box
        param_text = (f"Level (β₀): {level*100:.3f}%\n"
                     f"Slope (β₁): {slope*100:.3f}%\n"
                     f"Curvature (β₂): {curvature*100:.3f}%\n"
                     f"Tau (λ): {tau:.2f} years")
        
        ax1.text(0.02, 0.98, param_text, transform=ax1.transAxes, 
                verticalalignment='top', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
        
        # Show factor components if requested
        if show_components:
            # Calculate individual components
            term1 = (1 - np.exp(-self.plot_maturities / tau)) / (self.plot_maturities / tau)
            term2 = term1 - np.exp(-self.plot_maturities / tau)
            
            level_component = np.full_like(self.plot_maturities, level)
            slope_component = slope * term1
            curve_component = curvature * term2
            
            ax2.plot(self.plot_maturities, level_component * 100, 'g--', 
                    label=f'Level: {level*100:.3f}%', alpha=0.7)
            ax2.plot(self.plot_maturities, slope_component * 100, 'r--', 
                    label=f'Slope Component', alpha=0.7)
            ax2.plot(self.plot_maturities, curve_component * 100, 'm--', 
                    label=f'Curvature Component', alpha=0.7)
            
            ax2.set_xlabel('Maturity (Years)', fontsize=12)
            ax2.set_ylabel('Component Contribution (%)', fontsize=12)
            ax2.set_title('Nelson-Siegel Factor Components', fontsize=12, fontweight='bold')
            ax2.grid(True, alpha=0.3)
            ax2.legend(fontsize=10)
            ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        
        plt.tight_layout()
        plt.show()
    
    def create_educational_content(self) -> widgets.Widget:
        """
        Create educational content widget explaining the Nelson-Siegel model.
        
        Returns:
        --------
        widgets.Widget
            HTML widget with educational content
        """
        content = """
        <div style="background-color: #f0f8ff; padding: 15px; border-radius: 10px; margin: 10px 0;">
            <h3>📊 Nelson-Siegel Yield Curve Model</h3>
            
            <p>The Nelson-Siegel model represents yield curves using four interpretable parameters:</p>
            
            <h4>🔹 Model Components:</h4>
            <ul>
                <li><strong>Level (β₀)</strong>: Long-term yield level - represents long-term inflation expectations and credit risk</li>
                <li><strong>Slope (β₁)</strong>: Short-term component - captures monetary policy expectations and short-term dynamics</li>
                <li><strong>Curvature (β₂)</strong>: Medium-term component - reflects supply/demand imbalances in medium maturities</li>
                <li><strong>Tau (λ)</strong>: Decay parameter - controls where the curvature effect is strongest</li>
            </ul>
            
            <h4>🔹 Economic Interpretation:</h4>
            <ul>
                <li><strong>Positive Slope</strong>: Upward sloping curve (normal) - higher long-term rates</li>
                <li><strong>Negative Slope</strong>: Inverted curve - often signals recession expectations</li>
                <li><strong>Positive Curvature</strong>: Humped shape - intermediate rates higher than short and long rates</li>
                <li><strong>Negative Curvature</strong>: U-shape - intermediate rates lower than short and long rates</li>
            </ul>
            
            <h4>🔹 Interactive Controls:</h4>
            <p>Use the sliders below to explore how each parameter affects the yield curve shape and observe their economic implications.</p>
        </div>
        """
        
        return widgets.HTML(value=content)
    
    def create_bond_comparison_widget(self) -> widgets.Widget:
        """
        Create widget for comparing different bond types.
        
        Returns:
        --------
        widgets.Widget
            Interactive comparison widget
        """
        if self.bond_type == 'treasury':
            content = """
            <div style="background-color: #fff5ee; padding: 15px; border-radius: 10px; margin: 10px 0;">
                <h4>🏛️ Treasury Bonds (Nominal Yields)</h4>
                <p><strong>Characteristics:</strong></p>
                <ul>
                    <li>Represent nominal interest rates (including inflation expectations)</li>
                    <li>Typically positive across all maturities</li>
                    <li>Level usually 2-6% in normal market conditions</li>
                    <li>Slope can be positive (normal) or negative (inverted)</li>
                </ul>
                
                <p><strong>Economic Signals:</strong></p>
                <ul>
                    <li><strong>Rising Level</strong>: Higher inflation expectations or increased risk premiums</li>
                    <li><strong>Steepening</strong>: Expectations of economic growth and/or rising inflation</li>
                    <li><strong>Flattening/Inversion</strong>: Recession fears or aggressive monetary tightening</li>
                </ul>
            </div>
            """
        else:
            content = """
            <div style="background-color: #f0fff0; padding: 15px; border-radius: 10px; margin: 10px 0;">
                <h4>🛡️ TIPS (Real Yields)</h4>
                <p><strong>Characteristics:</strong></p>
                <ul>
                    <li>Represent real interest rates (inflation-adjusted)</li>
                    <li>Can be negative during periods of low real growth</li>
                    <li>Level typically -1% to +3% in recent years</li>
                    <li>Less volatile than nominal yields</li>
                </ul>
                
                <p><strong>Economic Signals:</strong></p>
                <ul>
                    <li><strong>Negative Real Yields</strong>: Low economic growth expectations</li>
                    <li><strong>Rising Real Yields</strong>: Improving growth prospects</li>
                    <li><strong>TIPS vs Treasury Spread</strong>: Implied inflation expectations</li>
                </ul>
            </div>
            """
        
        return widgets.HTML(value=content)
    
    def create_full_interactive_dashboard(self) -> widgets.Widget:
        """
        Create a comprehensive interactive dashboard.
        
        Returns:
        --------
        widgets.Widget
            Complete interactive dashboard
        """
        # Load current market data
        self.load_current_data()
        
        # Create widgets
        param_widgets = self.create_parameter_widgets()
        educational_content = self.create_educational_content()
        bond_content = self.create_bond_comparison_widget()
        
        # Create the interactive plot
        interactive_plot = widgets.interactive(
            self.plot_interactive_curve,
            level=param_widgets['level'],
            slope=param_widgets['slope'],
            curvature=param_widgets['curvature'],
            tau=param_widgets['tau'],
            show_market=param_widgets['show_market'],
            show_components=param_widgets['show_components']
        )
        
        # Organize layout
        controls = widgets.VBox([
            widgets.HTML('<h3>🎛️ Parameter Controls</h3>'),
            param_widgets['level'],
            param_widgets['slope'],
            param_widgets['curvature'],
            param_widgets['tau'],
            widgets.HTML('<h4>📈 Display Options</h4>'),
            param_widgets['show_market'],
            param_widgets['show_components']
        ])
        
        # Main dashboard layout
        dashboard = widgets.VBox([
            educational_content,
            bond_content,
            widgets.HBox([controls, interactive_plot.children[-1]]),
            widgets.VBox(interactive_plot.children[:-1])
        ])
        
        return dashboard


class HistoricalFactorExplorer:
    """
    Interactive explorer for historical Nelson-Siegel factors.
    """
    
    def __init__(self, fred_api_key: Optional[str] = None):
        """Initialize the historical factor explorer."""
        if not HAS_IPYWIDGETS:
            raise ImportError("ipywidgets is required for interactive functionality.")
        
        self.data_manager = DataManager(fred_api_key)
        self.treasury_factors = None
        self.tips_factors = None
    
    def load_historical_data(self, start_date: str = '2010-01-01', 
                           end_date: Optional[str] = None):
        """
        Load historical factor data for both Treasury and TIPS.
        
        Parameters:
        -----------
        start_date : str
            Start date for historical analysis
        end_date : str, optional
            End date for historical analysis
        """
        from .analysis import YieldCurveAnalyzer
        
        analyzer = YieldCurveAnalyzer(self.data_manager.treasury_downloader.api_key)
        
        print("Loading Treasury historical factors...")
        self.treasury_factors = analyzer.analyze_historical_factors(
            'treasury', start_date, end_date
        )
        
        print("Loading TIPS historical factors...")
        self.tips_factors = analyzer.analyze_historical_factors(
            'tips', start_date, end_date
        )
    
    def create_historical_dashboard(self) -> widgets.Widget:
        """
        Create interactive dashboard for historical factor analysis.
        
        Returns:
        --------
        widgets.Widget
            Historical analysis dashboard
        """
        # Load data if not already loaded
        if self.treasury_factors is None or self.tips_factors is None:
            self.load_historical_data()
        
        # Create control widgets
        factor_selector = widgets.Dropdown(
            options=['Level', 'Slope', 'Curvature', 'Tau'],
            value='Level',
            description='Factor:',
            style={'description_width': 'initial'}
        )
        
        bond_selector = widgets.SelectMultiple(
            options=['Treasury', 'TIPS'],
            value=['Treasury', 'TIPS'],
            description='Bond Types:',
            style={'description_width': 'initial'}
        )
        
        date_range = widgets.SelectionRangeSlider(
            options=self.treasury_factors.index.tolist(),
            index=(0, len(self.treasury_factors) - 1),
            description='Date Range:',
            style={'description_width': 'initial'}
        )
        
        def plot_historical_factors(factor, bond_types, date_range_indices):
            """Plot historical factors based on selections."""
            plt.figure(figsize=(14, 8))
            
            start_idx, end_idx = date_range_indices
            start_date = self.treasury_factors.index[start_idx]
            end_date = self.treasury_factors.index[end_idx]
            
            if 'Treasury' in bond_types:
                data = self.treasury_factors.loc[start_date:end_date, factor]
                if factor != 'Tau':
                    data = data * 100
                plt.plot(data.index, data.values, label='Treasury', linewidth=2, alpha=0.8)
            
            if 'TIPS' in bond_types:
                # Align TIPS data with Treasury date range
                tips_aligned = self.tips_factors.loc[
                    self.tips_factors.index.intersection(
                        self.treasury_factors.loc[start_date:end_date].index
                    )
                ]
                if len(tips_aligned) > 0:
                    data = tips_aligned[factor]
                    if factor != 'Tau':
                        data = data * 100
                    plt.plot(data.index, data.values, label='TIPS', linewidth=2, alpha=0.8)
            
            plt.title(f'Historical {factor} Factor Evolution', fontsize=16, fontweight='bold')
            plt.xlabel('Date', fontsize=12)
            
            unit = 'Years' if factor == 'Tau' else '%'
            plt.ylabel(f'{factor} ({unit})', fontsize=12)
            
            plt.legend(fontsize=12)
            plt.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.show()
        
        # Create interactive plot
        interactive_historical = widgets.interactive(
            plot_historical_factors,
            factor=factor_selector,
            bond_types=bond_selector,
            date_range_indices=date_range
        )
        
        # Educational content for historical analysis
        historical_content = widgets.HTML(value="""
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; margin: 10px 0;">
            <h3>📈 Historical Factor Analysis</h3>
            <p>Explore how Nelson-Siegel factors have evolved over time and their relationship to economic events:</p>
            
            <h4>🔹 Key Historical Patterns:</h4>
            <ul>
                <li><strong>2008 Financial Crisis</strong>: Sharp drop in levels, negative slopes</li>
                <li><strong>QE Periods</strong>: Compressed levels, flatter curves</li>
                <li><strong>Taper Tantrum (2013)</strong>: Rapid level increases, steepening</li>
                <li><strong>COVID-19 (2020)</strong>: Historic lows, extreme curve shapes</li>
            </ul>
            
            <h4>🔹 Factor Relationships:</h4>
            <ul>
                <li><strong>Level</strong>: Follows long-term inflation expectations and growth</li>
                <li><strong>Slope</strong>: Reflects monetary policy stance and cycle expectations</li>
                <li><strong>Treasury vs TIPS</strong>: Spread indicates inflation expectations</li>
            </ul>
        </div>
        """)
        
        # Combine into dashboard
        controls = widgets.VBox([
            widgets.HTML('<h3>🎛️ Historical Analysis Controls</h3>'),
            factor_selector,
            bond_selector,
            date_range
        ])
        
        dashboard = widgets.VBox([
            historical_content,
            widgets.HBox([controls, interactive_historical.children[-1]]),
            widgets.VBox(interactive_historical.children[:-1])
        ])
        
        return dashboard


def create_yield_curve_tutorial() -> widgets.Widget:
    """
    Create a comprehensive tutorial widget for yield curve analysis.
    
    Returns:
    --------
    widgets.Widget
        Complete tutorial interface
    """
    if not HAS_IPYWIDGETS:
        raise ImportError("ipywidgets is required for tutorial functionality.")
    
    tutorial_content = widgets.HTML(value="""
    <div style="background-color: #e8f4fd; padding: 20px; border-radius: 15px; margin: 15px 0;">
        <h2>🎓 Yield Curve Analysis Tutorial</h2>
        
        <h3>📚 What is a Yield Curve?</h3>
        <p>A yield curve shows the relationship between interest rates (yields) and time to maturity for bonds of similar credit quality. 
        It's one of the most important tools in finance and economics.</p>
        
        <h3>🔍 Why is it Important?</h3>
        <ul>
            <li><strong>Economic Indicator</strong>: Predicts recessions, inflation, and economic growth</li>
            <li><strong>Monetary Policy</strong>: Shows market expectations of central bank actions</li>
            <li><strong>Investment Decisions</strong>: Guides bond portfolio construction and risk management</li>
            <li><strong>Pricing Models</strong>: Foundation for valuing interest rate derivatives</li>
        </ul>
        
        <h3>📊 Yield Curve Shapes and Their Meanings:</h3>
        <ul>
            <li><strong>Normal (Upward Sloping)</strong>: Long-term rates > short-term rates. Indicates healthy economic expectations.</li>
            <li><strong>Inverted (Downward Sloping)</strong>: Short-term rates > long-term rates. Often precedes recessions.</li>
            <li><strong>Flat</strong>: Similar rates across maturities. Indicates economic uncertainty or transition.</li>
            <li><strong>Humped</strong>: Medium-term rates highest. Unusual shape indicating specific market conditions.</li>
        </ul>
        
        <h3>🏛️ Treasury vs TIPS:</h3>
        <ul>
            <li><strong>Treasury Securities</strong>: Show nominal yields (includes inflation expectations)</li>
            <li><strong>TIPS (Treasury Inflation-Protected Securities)</strong>: Show real yields (inflation-adjusted)</li>
            <li><strong>Breakeven Inflation</strong>: Treasury yield - TIPS yield = market's inflation expectations</li>
        </ul>
        
        <h3>⚡ Nelson-Siegel Model Benefits:</h3>
        <ul>
            <li><strong>Parsimonious</strong>: Only 4 parameters describe entire curve</li>
            <li><strong>Interpretable</strong>: Each parameter has clear economic meaning</li>
            <li><strong>Flexible</strong>: Can capture various curve shapes</li>
            <li><strong>Stable</strong>: Smooth, well-behaved fitted curves</li>
        </ul>
        
        <h3>🎯 Practical Applications:</h3>
        <ol>
            <li><strong>Bond Pricing</strong>: Estimate fair value for bonds not actively traded</li>
            <li><strong>Risk Management</strong>: Identify cheap/expensive bonds relative to the curve</li>
            <li><strong>Economic Forecasting</strong>: Track factor evolution to predict economic changes</li>
            <li><strong>Portfolio Management</strong>: Optimize bond portfolios based on factor exposures</li>
        </ol>
    </div>
    """)
    
    return tutorial_content
