#!/usr/bin/env python3
"""
Command-line interface for offer analytics.
Provides queries for weekly summaries, best offers, and industry filtering.
"""

import sys
import os
import argparse
import json
from datetime import datetime

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from src.extraction.analytics import (
    get_weekly_offers_by_industry,
    get_best_offers_per_week,
    get_industry_summary,
    get_weekly_aggregation,
    get_available_industries
)


def format_offer(offer: dict) -> str:
    """Format a single offer for display."""
    discount_str = ""
    if offer["discount_type"] == "PERCENT":
        discount_str = f"{offer['percent_off']:.1f}% off"
        if offer.get("is_up_to"):
            discount_str = f"Up to {discount_str}"
    elif offer["discount_type"] == "AMOUNT":
        currency = offer.get("currency", "$")
        discount_str = f"{currency}{offer['amount_off']:.2f} off"
    elif offer["discount_type"] == "FREE_SHIP":
        discount_str = "Free Shipping"
    
    conditions = []
    if offer.get("min_spend"):
        conditions.append(f"Min spend: {offer['currency']}{offer['min_spend']:.2f}")
    if offer.get("promo_code"):
        conditions.append(f"Code: {offer['promo_code']}")
    
    conditions_str = f" ({', '.join(conditions)})" if conditions else ""
    
    return (
        f"Week {offer['iso_week']:2d} | {offer['company_name']:30s} | "
        f"{discount_str:20s}{conditions_str}"
    )


def print_weekly_summary(iso_year: int, industry: str = None, use_db_prefix: bool = False):
    """Print weekly aggregation summary."""
    print(f"\n{'='*80}")
    print(f"Weekly Offer Summary - {iso_year}")
    if industry:
        print(f"Industry Filter: {industry}")
    print(f"{'='*80}\n")
    
    results = get_weekly_aggregation(iso_year, industry, use_db_prefix)
    
    if not results:
        print("No offers found for the specified criteria.")
        return
    
    print(f"{'Week':<6} {'Industry':<30} {'Offers':<8} {'Emails':<8} {'Avg %':<8} {'Max %':<8} {'Min %':<8}")
    print("-" * 80)
    
    for row in results:
        avg_pct = f"{row['avg_percent_off']:.1f}%" if row['avg_percent_off'] else "N/A"
        max_pct = f"{row['max_percent_off']:.1f}%" if row['max_percent_off'] else "N/A"
        min_pct = f"{row['min_percent_off']:.1f}%" if row['min_percent_off'] else "N/A"
        industry_name = row['primary_industry'] or "N/A"
        
        print(
            f"{row['iso_week']:<6} "
            f"{industry_name:<30} "
            f"{row['total_offers']:<8} "
            f"{row['emails_with_offers']:<8} "
            f"{avg_pct:<8} "
            f"{max_pct:<8} "
            f"{min_pct:<8}"
        )


def print_best_offers(iso_year: int, top_n: int = 10, industry: str = None, 
                     use_db_prefix: bool = False, week: int = None):
    """Print best offers per week."""
    print(f"\n{'='*80}")
    print(f"Best Offers Per Week - {iso_year}")
    if industry:
        print(f"Industry Filter: {industry}")
    if week:
        print(f"Week Filter: {week}")
    print(f"Top {top_n} offers per week")
    print(f"{'='*80}\n")
    
    offers = get_best_offers_per_week(iso_year, top_n, industry, use_db_prefix)
    
    if week:
        offers = [o for o in offers if o['iso_week'] == week]
    
    if not offers:
        print("No offers found for the specified criteria.")
        return
    
    current_week = None
    for offer in offers:
        if current_week != offer['iso_week']:
            if current_week is not None:
                print()
            current_week = offer['iso_week']
            print(f"\n--- Week {current_week} (Rank {offer['week_rank']}) ---")
        
        print(format_offer(offer))


def print_industry_summary(iso_year: int, industry: str = None, use_db_prefix: bool = False):
    """Print industry summary statistics."""
    print(f"\n{'='*80}")
    print(f"Industry Summary - {iso_year}")
    if industry:
        print(f"Industry Filter: {industry}")
    else:
        print("All Industries")
    print(f"{'='*80}\n")
    
    summary = get_industry_summary(iso_year, industry, use_db_prefix)
    
    if not summary or summary.get('total_offers', 0) == 0:
        print("No offers found for the specified criteria.")
        return
    
    print(f"Total Offers: {summary['total_offers']:,}")
    print(f"Emails with Offers: {summary['emails_with_offers']:,}")
    print(f"Weeks with Offers: {summary['weeks_with_offers']}")
    print(f"\nDiscount Statistics:")
    print(f"  Average % Off: {summary['avg_percent_off']:.2f}%" if summary['avg_percent_off'] else "  Average % Off: N/A")
    print(f"  Maximum % Off: {summary['max_percent_off']:.1f}%" if summary['max_percent_off'] else "  Maximum % Off: N/A")
    print(f"  Minimum % Off: {summary['min_percent_off']:.1f}%" if summary['min_percent_off'] else "  Minimum % Off: N/A")
    print(f"\nOffer Type Breakdown:")
    print(f"  Percent Offers: {summary['percent_offers']:,}")
    print(f"  Amount Offers: {summary['amount_offers']:,}")
    print(f"  Free Shipping Offers: {summary['free_ship_offers']:,}")


def list_industries(use_db_prefix: bool = False):
    """List all available industries."""
    print("\nAvailable Industries:")
    print("-" * 40)
    
    industries = get_available_industries(use_db_prefix)
    
    if not industries:
        print("No industries found.")
        return
    
    for industry in industries:
        print(f"  - {industry}")


def export_to_json(iso_year: int, output_file: str, industry: str = None, 
                   use_db_prefix: bool = False, query_type: str = "best_offers"):
    """Export query results to JSON file."""
    if query_type == "best_offers":
        data = get_best_offers_per_week(iso_year, top_n=100, industry=industry, use_db_prefix=use_db_prefix)
    elif query_type == "weekly_summary":
        data = get_weekly_aggregation(iso_year, industry, use_db_prefix)
    elif query_type == "industry_summary":
        data = get_industry_summary(iso_year, industry, use_db_prefix)
    else:
        print(f"Unknown query type: {query_type}")
        return
    
    # Convert datetime objects to strings for JSON serialization
    def json_serial(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2, default=json_serial)
    
    print(f"\n✅ Exported {len(data) if isinstance(data, list) else 1} records to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Analytics CLI for offer extraction data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show weekly summary for 2025
  python analytics_cli.py --weekly-summary --year 2025

  # Show best offers per week for a specific industry
  python analytics_cli.py --best-offers --year 2025 --industry "Technology"

  # Show best offers for a specific week
  python analytics_cli.py --best-offers --year 2025 --week 5

  # Export best offers to JSON
  python analytics_cli.py --best-offers --year 2025 --export results.json

  # List all available industries
  python analytics_cli.py --list-industries
        """
    )
    
    parser.add_argument("--year", type=int, default=2025,
                       help="ISO year (default: 2025)")
    parser.add_argument("--week", type=int,
                       help="ISO week (1-52) to filter by")
    parser.add_argument("--industry", type=str,
                       help="Industry name to filter by (checks primary, secondary, tertiary)")
    parser.add_argument("--top-n", type=int, default=10,
                       help="Number of top offers per week (default: 10)")
    parser.add_argument("--use-db-prefix", action="store_true",
                       help="Use DB_* environment variables for connection")
    parser.add_argument("--export", type=str,
                       help="Export results to JSON file")
    
    # Query type flags
    parser.add_argument("--weekly-summary", action="store_true",
                       help="Show weekly aggregation summary")
    parser.add_argument("--best-offers", action="store_true",
                       help="Show best offers per week")
    parser.add_argument("--industry-summary", action="store_true",
                       help="Show industry summary statistics")
    parser.add_argument("--list-industries", action="store_true",
                       help="List all available industries")
    
    args = parser.parse_args()
    
    # If export is specified, determine query type
    if args.export:
        query_type = "best_offers"
        if args.weekly_summary:
            query_type = "weekly_summary"
        elif args.industry_summary:
            query_type = "industry_summary"
        
        export_to_json(args.year, args.export, args.industry, 
                      args.use_db_prefix, query_type)
        return
    
    # Execute query based on flags
    if args.list_industries:
        list_industries(args.use_db_prefix)
    elif args.weekly_summary:
        print_weekly_summary(args.year, args.industry, args.use_db_prefix)
    elif args.best_offers:
        print_best_offers(args.year, args.top_n, args.industry, 
                         args.use_db_prefix, args.week)
    elif args.industry_summary:
        print_industry_summary(args.year, args.industry, args.use_db_prefix)
    else:
        # Default: show best offers
        print_best_offers(args.year, args.top_n, args.industry, 
                         args.use_db_prefix, args.week)


if __name__ == "__main__":
    main()

